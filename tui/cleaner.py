"""Read-only discovery and explicitly authorized developer cleanup.

Policy-based native commands, not arbitrary paths or shell expressions.
Docker commands are pinned to a local Unix endpoint for each operation.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import hashlib
import re
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from tui.operation_lock import operation_lock


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
            "All unused Engine builder cache older than 7 days; future builds may be slower.",
            "docker", ("builder", "prune", "--all", "--force", "--filter", "until=168h")),
    Cleaner("docker-dangling-images", "Docker dangling images", "DOCKER", True,
            "All dangling images; Docker protects container references.",
            "docker", ("image", "prune", "--force")),
    Cleaner("docker-unused-images", "Docker unused tagged images", "DOCKER / MANUAL", False,
            "Select individual unused tagged image IDs; no forced removal or bulk prune.",
            "docker", ()),
    Cleaner("docker-volumes", "Docker unused local volumes", "DOCKER / MANUAL", False,
            "PERMANENT DATA LOSS: select individual unused local volumes. Back up first.",
            "docker", ()),
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
    Cleaner("uv-cache-clean", "uv full cache", "PACKAGE CACHES / MANUAL", False,
            "Clear all uv cache entries; may break symlink-mode environments.",
            "uv", ("cache", "clean")),
    Cleaner("devbox-logs", "Devbox logs older than 30 days", "DEVBOX / MANUAL", False,
            "Delete old Devbox run logs and event files only; history older than 30 days is lost.",
            "", ()),
)
BY_KEY = {item.key: item for item in CLEANERS}
ORDER = tuple(BY_KEY)
SAFE_KEYS = frozenset(item.key for item in CLEANERS if item.safe)
RESOURCE_KEYS = {"docker-unused-images": "image", "docker-volumes": "volume"}


@dataclass(frozen=True)
class Scan:
    key: str
    available: bool
    estimate: str
    note: str
    resources: tuple = ()
    endpoint: str = ""


@dataclass(frozen=True)
class Outcome:
    state: str
    detail: str


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


def checked(argv, *, timeout=12):
    result = run(argv, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Command unavailable or failed: " + " ".join(argv))
    return result.stdout.strip()


def docker_prefix():
    # Explicit DOCKER_HOST is accepted only if local. DOCKER_CONTEXT takes
    # precedence in Docker; inspect its endpoint instead of guessing.
    endpoint = os.environ.get("DOCKER_HOST", "")
    if os.environ.get("DOCKER_CONTEXT") or not endpoint:
        context = checked(["docker", "context", "show"], timeout=3)
        if not context:
            raise RuntimeError("No Docker context")
        endpoint = checked(["docker", "context", "inspect", "--format",
                            "{{.Endpoints.docker.Host}}", context], timeout=3)
    if not endpoint.startswith("unix:///") or "\n" in endpoint:
        raise RuntimeError("Remote/non-Unix Docker endpoint refused")
    # An explicit --context conflicts with --host; the CLI flag pins the host.
    if not Path(endpoint[len("unix://"):]).is_socket():
        raise RuntimeError("Local Docker socket unavailable")
    return ["docker", "--host", endpoint]


def docker_df(prefix):
    output = checked(prefix + ["system", "df", "--format", "{{json .}}"])
    return {row["Type"]: row for row in (json.loads(line) for line in output.splitlines())}


def size_bytes(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        return None
    if not path.exists():
        return 0 if path.parent.is_dir() else None
    if not path.is_dir():
        return None
    try:
        result = run(["du", "-sx", "--block-size=1", "--", str(path)])
        if result.returncode:
            return None
        return int(result.stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        # Failure to measure a verified cache must not make it unavailable.
        return None


def size(path):
    value = size_bytes(path)
    return human(value) if value is not None else "unknown"


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


# Keep slow individual-resource inventory separate from the All-safe probe.
PROBE_GROUPS = {
    "docker": tuple(item.key for item in CLEANERS if item.tool == "docker" and item.safe),
    "docker-manual": tuple(RESOURCE_KEYS),
    **{item.key: (item.key,) for item in CLEANERS if item.tool != "docker"},
}
PROBE_CONCURRENCY = 4
PROBE_TIMEOUT = 30


def pip_cache_command():
    """Prefer the system interpreter; fall back to a user-installed pip CLI."""
    candidates = [["python3", "-m", "pip"], ["pip3"], ["pip"]]
    for argv in candidates:
        if not shutil.which(argv[0]):
            continue
        try:
            path = checked(argv + ["cache", "dir"], timeout=4)
            if path and Path(path).is_absolute():
                return argv, path
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("No working pip cache command (python3 -m pip, pip3, pip)")


def json_lines(prefix, args):
    return [json.loads(line) for line in checked(prefix + args, timeout=5).splitlines()]


def volume_token(prefix, row):
    # Bind a name to its inspected identity and endpoint; do not delete a
    # recreated volume with the same name. Native rm also checks references.
    stamp = hashlib.sha256(json.dumps(
        [prefix[-1], row], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return "volume:" + row["Name"] + ":" + stamp


def eligible_volume(row):
    return (row.get("Driver") == "local" and bool(row.get("CreatedAt"))
            and (row.get("Labels") or {}).get("devbox.protect") != "true"
            and not row.get("Options"))


def volume_sizes(prefix):
    """Optional sizes from the CLI; unsupported output never blocks selection."""
    output = checked(prefix + ["system", "df", "-v"], timeout=5)
    section = False
    sizes = {}
    for line in output.splitlines():
        if line.strip().startswith("Local Volumes space usage:"):
            section = True
            continue
        if not section:
            continue
        if line.strip().endswith("space usage:"):
            break
        fields = line.split()
        if len(fields) == 3 and fields[1].isdigit():
            sizes[fields[0]] = fields[2]
    return sizes


def docker_resources(prefix, key):
    if key == "docker-unused-images":
        containers = checked(prefix + ["container", "ls", "-aq"], timeout=4).splitlines()
        used = set()
        if containers:
            used = set(checked(prefix + ["container", "inspect", "--format", "{{.Image}}",
                                         *containers], timeout=5).splitlines())
        images = json_lines(prefix, ["image", "ls", "--no-trunc", "--filter", "dangling=false",
                                     "--format", "{{json .}}"])
        by_id = {}
        for row in images:
            ident = row["ID"]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", ident) or ident in used:
                continue
            label = row["Repository"] + ":" + row["Tag"]
            if "<none>" in label:
                continue
            if ident in by_id:
                by_id[ident]["label"] += ", " + label
            else:
                by_id[ident] = {"token": "image:" + ident, "label": label,
                                "size": row.get("Size", "unknown")}
        return tuple(by_id.values())
    names = checked(prefix + ["volume", "ls", "--filter", "dangling=true",
                              "--format", "{{.Name}}"], timeout=4).splitlines()
    if not names:
        return ()
    volumes = json.loads(checked(prefix + ["volume", "inspect", *names], timeout=5))
    return tuple({"token": volume_token(prefix, row), "label": row["Name"],
                  "size": "unknown"} for row in volumes if eligible_volume(row))


def resource_kind(token):
    if re.fullmatch(r"image:sha256:[a-f0-9]{64}", token):
        return "image"
    if re.fullmatch(r"volume:[a-zA-Z0-9][a-zA-Z0-9_.-]*:[a-f0-9]{64}", token):
        return "volume"
    raise ValueError("Invalid resource token")


def validate_resources(keys, resources, *, required=True):
    kinds = [resource_kind(token) for token in resources]
    expected = {RESOURCE_KEYS[key] for key in keys if key in RESOURCE_KEYS}
    if len(set(resources)) != len(resources) or set(kinds) - expected:
        raise ValueError("Duplicate resource or resource does not match selected cleaner")
    if required and expected - set(kinds):
        raise ValueError("Select individual image/volume resources; bulk removal is disabled")


def scan_group(group, docker_target=None, *, measure=True):
    keys = PROBE_GROUPS[group]
    rows = []
    docker, docker_error = {}, ""
    if group in {"docker", "docker-manual"} and shutil.which("docker"):
        try:
            prefix = docker_target if docker_target is not None else docker_prefix()
            if measure and group == "docker":
                try:
                    docker = docker_df(prefix)
                    if not docker:
                        raise RuntimeError("Empty disk usage inventory")
                except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired):
                    # A slow/unsupported size query is not a daemon failure.
                    docker = {"verified": checked(prefix + ["info", "--format", "{{.ID}}"], timeout=5)}
            else:
                docker = {"verified": checked(prefix + ["info", "--format", "{{.ID}}"], timeout=5)}
            if not docker or not any(docker.values()):
                raise RuntimeError("Docker inventory unavailable")
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            docker = {}
            docker_error = str(exc)
    for key in keys:
        item = BY_KEY[key]
        try:
            if item.key != "pip-cache" and item.tool and not shutil.which(item.tool):
                rows.append(Scan(item.key, False, "-", "Tool not installed"))
                continue
            if item.tool == "docker":
                if not docker:
                    rows.append(Scan(item.key, False, "-", docker_error or "Docker unavailable"))
                    continue
                category = ("Build Cache" if item.key == "docker-build-cache" else
                            "Local Volumes" if item.key == "docker-volumes" else "Images")
                estimate = docker.get(category, {}).get("Reclaimable", "unknown") if measure else "not measured"
                resources = ()
                note = "Engine daemon inventory; estimates include shared layers and may overlap. Custom Buildx builders are not scanned."
                if item.key in RESOURCE_KEYS and measure:
                    try:
                        resources = docker_resources(prefix, item.key)
                        if item.key == "docker-volumes" and resources:
                            try:
                                sizes = volume_sizes(prefix)
                                resources = tuple(dict(row, size=sizes.get(row["label"], "unknown")) for row in resources)
                            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                                pass
                        note += f" {len(resources)} individually eligible resources."
                    except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                        note += f" Resource inventory unavailable: {exc}"
                    if not resources:
                        rows.append(Scan(item.key, False, "-", note + " No eligible resources.", (), prefix[-1]))
                        continue
                rows.append(Scan(item.key, True, estimate, note, resources, prefix[-1]))
                continue
            if item.key == "devbox-logs":
                estimate = human(sum(n for _, n in old_logs())) if measure else "not measured"
            else:
                commands = {
                        "npm-cache": ["npm", "config", "get", "cache"],
                    "uv-cache": ["uv", "cache", "dir"],
                    "uv-cache-clean": ["uv", "cache", "dir"],
                }
                if key == "pip-cache":
                    _, path = pip_cache_command()
                else:
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
        output, _ = await asyncio.wait_for(process.communicate(), 50 if group == "docker-manual" else PROBE_TIMEOUT)
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


def native_outcome(result, before=None, after=None, *, docker=True):
    if result.returncode:
        return Outcome("FAILED", f"exit {result.returncode}")
    # Docker reports actual reclaimed storage, not total cache-record size.
    match = re.search(r"(?:Total reclaimed space|Total):\s*([\d.]+)\s*([kKMGT]?B)\b",
                      result.stdout + "\n" + result.stderr) if docker else None
    if match:
        value = float(match.group(1))
        return Outcome("CLEANED" if value > 0 else "NO_RECLAIM",
                       f"Docker reported {match.group(1)} {match.group(2)}")
    if before is not None and after is not None:
        delta = before - after
        return Outcome("CLEANED" if delta > 0 else "NO_RECLAIM",
                       f"cache footprint change: {human(delta)} (not guaranteed disk reclaim)")
    return Outcome("COMPLETED", "command succeeded; reclaimed bytes unknown")


def cache_path(item):
    if item.key == "pip-cache":
        return pip_cache_command()[1]
    if item.key == "apt-cache":
        return "/var/cache/apt/archives"
    if item.key == "npm-cache":
        return checked(["npm", "config", "get", "cache"])
    if item.key.startswith("uv-cache"):
        return checked(["uv", "cache", "dir"])
    return None


def execute(item, docker_target=None, resources=()):
    if item.key == "devbox-logs":
        count = 0
        for path, _ in old_logs():
            path.unlink()
            count += 1
        return Outcome("CLEANED" if count else "NOTHING_TO_CLEAN",
                       f"removed {count} old log/event files; disk bytes unknown")
    if item.tool == "docker":
        if docker_target is None:
            raise RuntimeError("Docker target was not verified for this run")
        if item.key in RESOURCE_KEYS:
            kind = RESOURCE_KEYS[item.key]
            tokens = [token for token in resources if resource_kind(token) == kind]
            if not tokens:
                raise RuntimeError("Explicit resource selection required")
            # Fresh inventory verifies protection, references and volume identity.
            current = {row["token"] for row in docker_resources(docker_target, item.key)}
            removed, skipped, failed = 0, 0, 0
            for token in tokens:
                if token not in current:
                    print(f"Skipped changed or in-use resource: {token}")
                    skipped += 1
                    continue
                target = token.removeprefix("image:") if kind == "image" else token.split(":")[1]
                if kind == "volume":
                    # Recheck the exact volume immediately before rm; the daemon
                    # rejects referenced volumes even if they became active.
                    try:
                        inspected = json.loads(checked(docker_target + ["volume", "inspect", target], timeout=5))
                        if len(inspected) != 1 or not eligible_volume(inspected[0]) or volume_token(docker_target, inspected[0]) != token:
                            skipped += 1
                            continue
                    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired):
                        skipped += 1
                        continue
                argv = docker_target + [kind, "rm"] + (["--no-prune"] if kind == "image" else []) + [target]
                result = run(argv, timeout=900)
                print(result.stdout + result.stderr, flush=True)
                if result.returncode:
                    failed += 1
                else:
                    removed += 1
            return Outcome("FAILED" if failed else "SKIPPED" if skipped else "CLEANED",
                           f"{removed} removed, {skipped} skipped, {failed} failed; disk bytes unknown")
        argv = docker_target + list(item.command)
    elif item.key == "pip-cache":
        prefix, _ = pip_cache_command()
        argv = prefix + ["cache", "purge"]
    elif item.sudo:
        argv = ["sudo", "-n", item.tool, *item.command]
    else:
        argv = [item.tool, *item.command]
    try:
        path = cache_path(item)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        path = None  # Measurement is optional, not an execution prerequisite.
    before = size_bytes(path) if path else None
    print("+ " + " ".join(argv), flush=True)
    result = run(argv, timeout=900)
    print(result.stdout + result.stderr, flush=True)
    after = size_bytes(path) if path else None
    return native_outcome(result, before, after, docker=item.tool == "docker")


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
    parser.add_argument("--resource", action="append", default=[], help="exact resource token from inventory (repeatable)")
    parser.add_argument("--docker-endpoint", help="require the local endpoint shown in inventory")
    parser.add_argument("--yes", action="store_true", help="explicitly execute the selected policy")
    parser.add_argument("--allow-risky", action="store_true", help="acknowledge manually selected risky cleaners")
    args = parser.parse_args(argv)
    if args.probe_group:
        if args.only or args.all_safe or args.yes or args.allow_risky or args.json or args.scan or args.dry_run or args.resource or args.docker_endpoint:
            parser.error("Internal inventory probe cannot be combined with cleanup arguments")
        print(json.dumps([asdict(row) for row in scan_group(args.probe_group)]))
        return 0
    if args.resource and not args.only:
        parser.error("--resource requires explicit --only")
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
        try:
            validate_resources(keys, args.resource, required=args.yes)
        except ValueError as exc:
            parser.error(str(exc))
        if not args.yes:
            for token in args.resource:
                print(f"Selected resource: {token}")
            for key in keys:
                print(f"{key}: {BY_KEY[key].description}")
                event(key, "PLANNED")
            print("Preview only; eligibility is checked at execution.")
            return 0
    try:
        if args.yes:
            with operation_lock():
                return run_plan(args, parser, keys if args.only else [])
        return run_plan(args, parser, keys if args.only else [])
    except (OSError, RuntimeError) as exc:
        print(f"Cleanup unavailable: {exc}", file=sys.stderr)
        return 1


def run_plan(args, parser, keys):
    target = None
    requested = (keys if args.only else SAFE_KEYS if args.all_safe else ORDER)
    if any(BY_KEY[key].tool == "docker" for key in requested) and shutil.which("docker"):
        try:
            target = docker_prefix()
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    if args.docker_endpoint and (target is None or target[-1] != args.docker_endpoint):
        parser.error("Docker endpoint changed since selection; rescan required")
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
            for resource in row.resources:
                print(f"  {resource['label']}  {resource['size']}  {resource['token']}")
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
    if args.all_safe:
        for row in rows:
            if row.key in SAFE_KEYS and not row.available:
                print(f"Skipped {row.key}: {row.note}")
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
    outcomes = []
    for key in keys:
        if key not in available:
            reason = next((row.note for row in rows if row.key == key), "unavailable")
            print(f"Skipped {key}: {reason}")
            event(key, "SKIPPED")
            outcomes.append((key, Outcome("SKIPPED", reason)))
            failed = True
            continue
        event(key, "RUNNING")
        try:
            outcome = execute(BY_KEY[key], target, args.resource) if key in RESOURCE_KEYS else execute(BY_KEY[key], target)
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            outcome = Outcome("FAILED", str(exc))
        event(key, outcome.state)
        outcomes.append((key, outcome))
        failed |= outcome.state in {"FAILED", "SKIPPED"}
    print("\nCLEANUP SUMMARY (per cleaner)")
    for key, outcome in outcomes:
        print(f"{key}: {outcome.state} — {outcome.detail}")
    for path in locations:
        delta = shutil.disk_usage(path).free - before[path]
        print(f"Observed free-space change ({path}): {human(delta)}")
    if "microsoft" in os.uname().release.lower():
        print("WSL: Linux free space may not shrink the Windows VHDX automatically.")
        print("Check the Windows VHDX size separately. Stop WSL and follow Microsoft disk-compaction guidance manually; Devbox never shuts down WSL or compacts disks.")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
