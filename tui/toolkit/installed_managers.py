"""Recognize original user-writable installation providers without receipts."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PACKAGES = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code",
            "copilot": "@github/copilot", "opencode": "opencode-ai",
            "gemini": "@google/gemini-cli", "skills-cli": "skills"}
BINS = {"skills-cli": "skills"}


@dataclass(frozen=True)
class Route:
    kind: str
    prefix: str
    version: str = ""

    @property
    def label(self):
        return {"npm": "npm global (" + self.prefix + ")", "native": "Native updater",
                "pipx": "pipx", "cargo": "Cargo (official Git source)"}.get(self.kind, self.kind)


def read(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def npm_route(key, binary):
    if key not in PACKAGES or not binary.is_symlink() or binary.parent.name != "bin":
        return None
    prefix = binary.parent.parent
    root = prefix / "lib/node_modules" / PACKAGES[key]
    try:
        target = binary.resolve(strict=True)
        if not target.is_relative_to(root.resolve(strict=True)):
            return None
        data = json.loads((root / "package.json").read_text())
        spec = data.get("bin")
        entry = spec.get(BINS.get(key, key)) if isinstance(spec, dict) else spec
        if (data.get("name") != PACKAGES[key] or not isinstance(entry, str)
                or (root / entry).resolve(strict=True) != target):
            return None
        current = data.get("version")
        if not isinstance(current, str) or not current:
            return None
        if root.stat().st_uid == os.getuid() and os.access(root.parent, os.W_OK) and os.access(binary.parent, os.W_OK) and shutil.which("npm"):
            return Route("npm", str(prefix), current)
    except (OSError, ValueError, TypeError, RuntimeError):
        pass
    return None


def native_route(key, binary):
    home = Path.home()
    try:
        real = binary.resolve(strict=True)
        if real.stat().st_uid != os.getuid():
            return None
        if key == "claude" and binary == home / ".local/bin/claude" and real.is_relative_to(home / ".local/share/claude/versions"):
            return Route("native", str(binary))
        if key == "opencode" and binary == home / ".opencode/bin/opencode" and real == binary:
            return Route("native", str(binary))
    except (OSError, RuntimeError):
        pass
    return None


def pipx_route(key, binary):
    if key != "uv" or not shutil.which("pipx"):
        return None
    try:
        data = json.loads(read("pipx", "list", "--json"))
        info = data["venvs"][key]["metadata"]["main_package"]
        if info["package"] != key or info.get("package_or_url", key) != key:
            return None
        target = binary.resolve(strict=True)
        if any(isinstance(item, dict) and item.get("__Path__") == str(target) for item in info.get("app_paths", [])):
            return Route("pipx", str(binary), info.get("package_version", ""))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        pass
    return None


def cargo_route(key, binary):
    if key != "rtk" or not shutil.which("cargo"):
        return None
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo").expanduser()
    if binary != home / "bin/rtk" or binary.is_symlink():
        return None
    try:
        installs = json.loads((home / ".crates2.json").read_text())["installs"]
        matches = [name for name, info in installs.items() if name.startswith("rtk ")
                   and "(git+https://github.com/rtk-ai/rtk" in name and "rtk" in info.get("bins", [])]
        if len(matches) == 1 and binary.stat().st_uid == os.getuid():
            source = matches[0].split("(git+", 1)[1].split("#", 1)[0].rstrip(")")
            if source.rstrip("/") in ("https://github.com/rtk-ai/rtk", "https://github.com/rtk-ai/rtk.git"):
                return Route("cargo", str(home), matches[0].split()[1])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def detect(key, path):
    if not path or not Path(path).is_absolute():
        return None
    binary = Path(path)
    if binary.name != BINS.get(key, key):
        return None
    return npm_route(key, binary) or native_route(key, binary) or pipx_route(key, binary) or cargo_route(key, binary)


def execute(key, path, kind, prefix):
    active = shutil.which(BINS.get(key, key))
    route = detect(key, active)
    if active != path or not route or (route.kind, route.prefix) != (kind, prefix):
        raise ValueError("Active installation or update provider changed; refresh and review.")
    if kind == "npm":
        argv = ["npm", "update", "--global", "--prefix", prefix, "--no-audit", "--no-fund", PACKAGES[key]]
    elif kind == "native":
        argv = [path, "update"] if key == "claude" else [path, "upgrade"]
    elif kind == "pipx":
        argv = ["pipx", "upgrade", "uv"]
    elif kind == "cargo":
        argv = ["cargo", "install", "--root", prefix, "--git", "https://github.com/rtk-ai/rtk", "rtk", "--locked"]
    else:
        raise ValueError("Unsupported update provider.")
    subprocess.run(argv, check=True, timeout=600, stdin=subprocess.DEVNULL)
    if shutil.which(BINS.get(key, key)) != path or not detect(key, path):
        raise ValueError("Update finished, but active installation changed; refresh inventory.")
    print("Update command completed using " + route.label)


def main():
    if len(sys.argv) != 5 or os.geteuid() == 0:
        return 2
    try:
        execute(*sys.argv[1:])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("Update failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
