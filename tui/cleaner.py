"""Read-only discovery and explicitly authorized developer cleanup.

Policy-based native commands, not arbitrary paths or shell expressions.
Docker commands are pinned to a local Unix endpoint for each operation.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class Cleaner:
    key: str
    label: str
    group: str
    safe: bool
    description: str
    tool: str
    command: tuple[str, ...]
    sudo: bool = False


CLEANERS = (
    Cleaner("docker-build-cache", "Docker old build cache", "DOCKER", True,
            "Dangling build cache older than 7 days; future builds may be slower.",
            "docker", ("builder", "prune", "--force", "--filter", "until=168h")),
    Cleaner("docker-dangling-images", "Docker old dangling images", "DOCKER", True,
            "Dangling images older than 7 days; Docker protects container references.",
            "docker", ("image", "prune", "--force", "--filter", "until=168h")),
    Cleaner("docker-unused-images", "Docker unused tagged images", "DOCKER / MANUAL", False,
            "Unused images older than 7 days, including tagged local builds; may require rebuilding.",
            "docker", ("image", "prune", "--all", "--force", "--filter", "until=168h")),
    Cleaner("docker-volumes", "Docker unused local volumes", "DOCKER / MANUAL", False,
            "PERMANENT DATA LOSS: remove unused local volumes, including named volumes. Back up first.",
            "docker", ("volume", "prune", "--all", "--force", "--filter", "label!=devbox.protect=true")),
    Cleaner("pip-cache", "pip download cache", "PACKAGE CACHES", True,
            "Remove cached downloads, not installed packages.",
            "python3", ("-m", "pip", "cache", "purge")),
    Cleaner("npm-cache", "npm download cache", "PACKAGE CACHES", True,
            "Remove npm download cache; subsequent installs may download again.",
            "npm", ("cache", "clean", "--force")),
    Cleaner("apt-cache", "APT downloaded archives", "PACKAGE CACHES", True,
            "Remove downloaded package archives, not installed packages; requires sudo.",
            "apt-get", ("clean",), True),
    Cleaner("uv-cache", "uv unused cache", "PACKAGE CACHES / MANUAL", False,
            "Prune unused uv cache entries; symlink-mode environments can depend on cache files.",
            "uv", ("cache", "prune")),
    Cleaner("devbox-logs", "Devbox logs older than 30 days", "DEVBOX / MANUAL", False,
            "Delete old Devbox run logs and event files only; history older than 30 days is lost.",
            "", ()),
)
BY_KEY = {item.key: item for item in CLEANERS}
ORDER = tuple(BY_KEY)
SAFE_KEYS = frozenset(item.key for item in CLEANERS if item.safe)


@dataclass(frozen=True)
class Scan:
    key: str
    available: bool
    estimate: str
    note: str


def command_env(argv):
    env = os.environ.copy()
    if argv[:2] == ["docker", "--host"]:
        for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            env.pop(key, None)
    return env


def run(argv, *, timeout=12):
    """Capture native output; failures never become successful inventory."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, check=False, env=command_env(argv))


def checked(argv):
    result = run(argv)
    if result.returncode:
        raise RuntimeError("Command unavailable or failed: " + " ".join(argv))
    return result.stdout.strip()


def docker_prefix():
    # Explicit DOCKER_HOST is accepted only if local. DOCKER_CONTEXT takes
    # precedence in Docker; inspect its endpoint instead of guessing.
    endpoint = os.environ.get("DOCKER_HOST", "")
    if os.environ.get("DOCKER_CONTEXT") or not endpoint:
        context = checked(["docker", "context", "show"])
        if not context:
            raise RuntimeError("No Docker context")
        endpoint = checked(["docker", "context", "inspect", "--format",
                            "{{.Endpoints.docker.Host}}", context])
    if not endpoint.startswith("unix:///") or "\n" in endpoint:
        raise RuntimeError("Remote/non-Unix Docker endpoint refused")
    # An explicit --context conflicts with --host; the CLI flag pins the host.
    if not Path(endpoint[len("unix://"):]).is_socket():
        raise RuntimeError("Local Docker socket unavailable")
    return ["docker", "--host", endpoint]


def docker_df(prefix):
    output = checked(prefix + ["system", "df", "--format", "{{json .}}"])
    return {row["Type"]: row for row in (json.loads(line) for line in output.splitlines())}


def size(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        return "unknown"
    result = run(["du", "-sx", "--block-size=1", "--", str(path)])
    if result.returncode:
        return "unknown"
    return human(int(result.stdout.split()[0]))


def human(value):
    return f"{value / (1024 ** 2):,.1f} MiB"


def old_logs():
    root = Path.home() / ".local/state/devbox-bootstrap"
    cutoff = time.time() - 30 * 86400
    for folder, suffix in (("logs", ".log"), ("runs", ".events")):
        directory = root / folder
        # Never traverse redirected directories, including ancestor symlinks.
        if directory.resolve() != directory or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.suffix != suffix or path.is_symlink() or not path.is_file():
                continue
            stat = path.stat(follow_symlinks=False)
            if stat.st_mtime < cutoff:
                yield path, stat.st_blocks * 512


# Docker inventory is shared by its four rows; package probes are independent.
PROBE_GROUPS = {
    "docker": tuple(item.key for item in CLEANERS if item.tool == "docker"),
    **{item.key: (item.key,) for item in CLEANERS if item.tool != "docker"},
}
PROBE_CONCURRENCY = 4
PROBE_TIMEOUT = 30


def scan_group(group, docker_target=None, *, measure=True):
    keys = PROBE_GROUPS[group]
    rows = []
    docker, docker_error = {}, ""
    if group == "docker" and shutil.which("docker"):
        try:
            prefix = docker_target if docker_target is not None else docker_prefix()
            docker = docker_df(prefix) if measure else {"verified": checked(prefix + ["info", "--format", "{{.ID}}"])}
            if not docker or not any(docker.values()):
                raise RuntimeError("Docker inventory unavailable")
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            docker = {}
            docker_error = str(exc)
    for key in keys:
        item = BY_KEY[key]
        try:
            if item.tool and not shutil.which(item.tool):
                rows.append(Scan(item.key, False, "-", "Tool not installed"))
                continue
            if item.tool == "docker":
                if not docker:
                    rows.append(Scan(item.key, False, "-", docker_error or "Docker unavailable"))
                    continue
                category = ("Build Cache" if item.key == "docker-build-cache" else
                            "Local Volumes" if item.key == "docker-volumes" else "Images")
                estimate = docker.get(category, {}).get("Reclaimable", "unknown") if measure else "not measured"
                rows.append(Scan(item.key, True, estimate,
                                 "Docker category total; age filters and shared layers reduce actual reclaim."))
                continue
            if item.key == "devbox-logs":
                estimate = human(sum(n for _, n in old_logs())) if measure else "not measured"
            else:
                commands = {
                    "pip-cache": ["python3", "-m", "pip", "cache", "dir"],
                    "npm-cache": ["npm", "config", "get", "cache"],
                    "uv-cache": ["uv", "cache", "dir"],
                }
                path = checked(commands[key]) if key in commands else "/var/cache/apt/archives"
                estimate = size(path) if measure else "not measured"
            rows.append(Scan(item.key, True, estimate, "Cache footprint; not guaranteed reclaimable."))
        except (OSError, RuntimeError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            rows.append(Scan(item.key, False, "-", str(exc)))
    return rows


def scan(docker_target=None, *, keys=None, measure=True):
    requested = set(ORDER if keys is None else keys)
    return [row for group, members in PROBE_GROUPS.items() if requested.intersection(members)
            for row in scan_group(group, docker_target, measure=measure) if row.key in requested]


async def probe_group(group):
    """Isolated read-only worker. Kill its process group on timeout/cancel."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tui.cleaner", "--probe-group", group,
        cwd=Path(__file__).resolve().parents[1],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), PROBE_TIMEOUT)
        if process.returncode:
            raise RuntimeError("Inventory worker failed")
        rows = [Scan(**row) for row in json.loads(output)]
        if {row.key for row in rows} != set(PROBE_GROUPS[group]):
            raise RuntimeError("Incomplete inventory")
        return rows
    except (asyncio.TimeoutError, asyncio.CancelledError):
        # Child commands (docker, du, etc.) share the worker's process group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.communicate()
        raise


def select_keys(only, all_safe, available):
    if all_safe:
        return [key for key in ORDER if key in SAFE_KEYS and key in available]
    keys = only.split(",") if only else []
    if len(keys) != len(set(keys)) or any(key not in BY_KEY for key in keys):
        raise ValueError("Unknown or duplicate cleaner ID")
    return keys


def event(key, state):
    path = os.environ.get("DEVBOX_EVENT_FILE")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(f"STATUS\t{key}\t{state}\n")


def execute(item, docker_target=None):
    if item.key == "devbox-logs":
        # Recheck at execution time. unlink does not follow a file symlink.
        count = 0
        for path, _ in old_logs():
            path.unlink()
            count += 1
        print(f"Removed {count} old Devbox log/event files.")
        return True
    if item.tool == "docker":
        if docker_target is None:
            raise RuntimeError("Docker target was not verified for this run")
        argv = docker_target + list(item.command)
    elif item.sudo:
        argv = ["sudo", "-n", item.tool, *item.command]
    else:
        argv = [item.tool, *item.command]
    print("+ " + " ".join(argv), flush=True)
    return subprocess.run(argv, stdin=subprocess.DEVNULL, timeout=900, env=command_env(argv)).returncode == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Developer Cleaner (read-only by default)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", "--recommended", dest="all_safe", action="store_true",
                       help="select safe available cleaners only")
    group.add_argument("--only", help="comma-separated cleaner IDs")
    parser.add_argument("--probe-group", choices=PROBE_GROUPS, help=argparse.SUPPRESS)
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="explicitly execute the selected policy")
    parser.add_argument("--allow-risky", action="store_true", help="acknowledge manually selected risky cleaners")
    args = parser.parse_args(argv)
    if args.probe_group:
        if args.only or args.all_safe or args.yes or args.allow_risky or args.json or args.scan or args.dry_run:
            parser.error("Internal inventory probe cannot be combined with cleanup arguments")
        print(json.dumps([asdict(row) for row in scan_group(args.probe_group)]))
        return 0
    if args.allow_risky and (not args.only or args.all_safe):
        parser.error("--allow-risky requires explicit --only")
    if args.yes and (args.scan or args.json or args.dry_run or not (args.only or args.all_safe)):
        parser.error("--yes requires a selected cleanup, not a scan or dry-run")
    if args.json and (args.only or args.all_safe):
        parser.error("--json is for inventory only")
    if os.geteuid() == 0:
        parser.error("Run Devbox as a regular user, not root")
    # Explicit previews need no second inventory; the TUI already scanned.
    if args.only:
        try:
            keys = select_keys(args.only, False, set())
        except ValueError as exc:
            parser.error(str(exc))
        if args.yes and any(key not in SAFE_KEYS for key in keys) and not args.allow_risky:
            parser.error("Risky cleaners require explicit --only and --allow-risky")
        if not args.yes:
            for key in keys:
                print(f"{key}: {BY_KEY[key].description}")
                event(key, "PLANNED")
            print("Preview only; eligibility is checked at execution.")
            return 0
    target = None
    requested = (keys if args.only else SAFE_KEYS if args.all_safe else ORDER)
    if any(BY_KEY[key].tool == "docker" for key in requested) and shutil.which("docker"):
        try:
            target = docker_prefix()
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    rows = scan(target, keys=requested, measure=not args.yes)
    available = {row.key for row in rows if row.available}
    try:
        keys = select_keys(args.only, args.all_safe, available)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps([dict(asdict(row), safe=BY_KEY[row.key].safe) for row in rows]))
        return 0
    if not (args.only or args.all_safe):
        for row in rows:
            item = BY_KEY[row.key]
            print(f"{row.key:25} {'SAFE' if item.safe else 'MANUAL':7} "
                  f"{row.estimate:20} {row.note}")
        print("No changes. Use --all or --only to preview; add --yes to execute.")
        return 0
    if any(key not in SAFE_KEYS for key in keys) and args.yes and not args.allow_risky:
        parser.error("Risky cleaners require explicit --only and --allow-risky")
    for key in keys:
        item = BY_KEY[key]
        print(f"{key}: {item.description}", flush=True)
    if not args.yes:
        for key in keys:
            event(key, "PLANNED")
        print("Preview only; no changes.")
        return 0
    if not keys:
        print("No available cleaners selected.")
        return 0
    if any(BY_KEY[key].sudo and key in available for key in keys):
        if os.environ.get("DEVBOX_TUI_MODE") != "1":
            if subprocess.run(["sudo", "-v"]).returncode:
                return 1
    # Root and home may be different mounts. Delta is observational, not a
    # guarantee that all changes were caused by this job.
    locations = [Path("/"), Path.home()]
    locations = list({p.stat().st_dev: p for p in locations}.values())
    before = {p: shutil.disk_usage(p).free for p in locations}
    failed = False
    for key in keys:
        if key not in available:
            print(f"Skipped {key}: unavailable")
            event(key, "SKIPPED")
            failed = True
            continue
        event(key, "RUNNING")
        try:
            ok = execute(BY_KEY[key], target)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"{key}: {exc}")
            ok = False
        event(key, "CLEANED" if ok else "FAILED")
        failed |= not ok
    for path in locations:
        delta = shutil.disk_usage(path).free - before[path]
        print(f"Observed free-space change ({path}): {human(delta)}")
    print("WSL: Linux free space may not shrink the Windows VHDX automatically.")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
