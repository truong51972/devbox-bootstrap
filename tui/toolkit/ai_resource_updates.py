"""Targeted, read-only AI extension version discovery and explicit update.

Codex is the workspace default. Never refresh unrelated marketplaces, enable
disabled plugins, change pinned sources, or update all globally installed skills.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from tui.agent_status import tomllib
from .agent_setup import SKILLS

KIT = "truong51972/coding-kit"
PONYTAIL = "dietrichgebert/ponytail"
SKILL_NAMES = frozenset(name for name, _ in SKILLS)
SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Update:
    state: str = "Unknown"
    installed: str = ""
    candidate: str = ""
    reason: str = ""
    eligible: bool = False


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def run_read(*args, timeout=8):
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace",
                                stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def decode(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def official_source(value, repo):
    return isinstance(value, str) and value.casefold().rstrip("/") in {
        repo, "https://github.com/" + repo, "https://github.com/" + repo + ".git",
        "git@github.com:" + repo + ".git",
    }


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def skill_path(name):
    # Current Codex uses the shared user-global skills directory; older
    # installs used CODEX_HOME/skills. Prefer the canonical Skills CLI path.
    paths = (Path.home() / ".agents/skills" / name / "SKILL.md",
             codex_home() / "skills" / name / "SKILL.md")
    return next((p for p in paths if p.is_file()), paths[0])


def skill_lock():
    root = os.environ.get("XDG_STATE_HOME")
    path = Path(root) / "skills/.skill-lock.json" if root else Path.home() / ".agents/.skill-lock.json"
    data = read_json(path)
    rows = data.get("skills")
    return rows if isinstance(rows, dict) else {}


def kit_entry(name, entries):
    row = entries.get(name)
    if not isinstance(row, dict):
        return None
    if (row.get("sourceType") != "github" or not official_source(row.get("source"), KIT)
            or not official_source(row.get("sourceUrl"), KIT)
            or row.get("ref") not in (None, "", "main")
            or row.get("skillName") not in (None, name)
            or row.get("skillPath") not in ("skills/" + name, "skills/" + name + "/SKILL.md")
            or not SHA.fullmatch(str(row.get("skillFolderHash", "")))):
        return None
    return row


def kit_tree():
    raw = run_read("curl", "-fsSL", "--max-time", "8",
                   "https://api.github.com/repos/truong51972/coding-kit/git/trees/main?recursive=1", timeout=10)
    data = decode(raw)
    entries = data.get("tree")
    if data.get("truncated") is not False or not isinstance(entries, list):
        return {}
    return {r["path"]: r["sha"] for r in entries if isinstance(r, dict)
            and r.get("type") == "tree" and isinstance(r.get("path"), str)
            and SHA.fullmatch(str(r.get("sha", "")))}


def skill_update(name, entries, tree):
    entry = kit_entry(name, entries)
    if name not in SKILL_NAMES or not skill_path(name).is_file():
        return Update(reason="Global skill not installed.")
    if not entry:
        return Update(reason="Skill source, scope or revision not verified; preserve existing files.")
    current = entry["skillFolderHash"]
    latest = tree.get("skills/" + name, "")
    if not latest:
        return Update(installed=current, reason="Upstream skill revision unavailable.")
    return Update("Current" if current == latest else "Available", current, latest,
                  "Global Skills CLI lockfile and official Coding Kit folder revision.", bool(shutil.which("skills")))


def ponytail_config():
    if tomllib is None:
        return False
    try:
        with (codex_home() / "config.toml").open("rb") as f:
            config = tomllib.load(f)
        marketplace = config["marketplaces"]["ponytail"]
        plugin = config["plugins"]["ponytail@ponytail"]
        return (marketplace.get("source_type") == "git"
                and official_source(marketplace.get("source"), PONYTAIL)
                and not any(marketplace.get(k) for k in ("ref", "ref_name", "sha", "sparse_paths"))
                and plugin.get("enabled", True) is True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def ponytail_installed_version():
    # CLI inventory identifies the active installation, unlike old cache folders.
    payload = decode(run_read("codex", "plugin", "list", "--json", "--marketplace", "ponytail", timeout=12))
    if payload.get("error") or payload.get("errors"):
        return ""
    rows = payload.get("installed", [])
    if isinstance(rows, list):
        matches = [r for r in rows if isinstance(r, dict)
                   and r.get("pluginId", r.get("id")) == "ponytail@ponytail"
                   and r.get("installed", True) is True and r.get("enabled", True) is True]
        if len(matches) == 1:
            v = matches[0].get("version")
            if isinstance(v, str) and SEMVER.fullmatch(v):
                return v
    # Older Codex may time out or omit version. Only use a unique verified
    # cache manifest; multiple historical versions cannot identify the active one.
    cache = codex_home() / "plugins/cache/ponytail/ponytail"
    try:
        dirs = [d for d in cache.iterdir() if d.is_dir() and not d.is_symlink()]
    except OSError:
        return ""
    if len(dirs) != 1:
        return ""
    for manifest in (".codex-plugin/plugin.json", "plugin.json"):
        data = read_json(dirs[0] / manifest)
        v = data.get("version")
        if (data.get("name") == "ponytail" and isinstance(v, str) and SEMVER.fullmatch(v)
                and v.removeprefix("v") == dirs[0].name.removeprefix("v")
                and official_source(data.get("repository") or data.get("homepage"), PONYTAIL)):
            return v
    return ""


def ponytail_update():
    if not shutil.which("codex") or not ponytail_config():
        return Update(reason="Codex Ponytail is disabled, pinned, or its official marketplace is not verified.")
    current = ponytail_installed_version()
    if not current:
        return Update(reason="Active Codex plugin version could not be verified.")
    data = decode(run_read("curl", "-fsSL", "--max-time", "8",
                           "https://raw.githubusercontent.com/DietrichGebert/ponytail/main/.codex-plugin/plugin.json", timeout=10))
    latest = data.get("version", "")
    if (data.get("name") != "ponytail" or not isinstance(latest, str) or not SEMVER.fullmatch(latest)
            or not official_source(data.get("repository") or data.get("homepage"), PONYTAIL)):
        return Update(installed=current, reason="Official upstream manifest unavailable.")
    state = "Available" if tuple(map(int, SEMVER.fullmatch(latest).groups())) > tuple(map(int, SEMVER.fullmatch(current).groups())) else "Current"
    return Update(state, current, latest, "Codex user marketplace; hooks trust remains manual.", True)


def execute(key):
    if key == "ponytail":
        before = ponytail_update()
        if before.state == "Current":
            print("Ponytail is already current.")
            return
        if before.state != "Available" or not before.eligible:
            raise ValueError("Ponytail update cannot be verified; refresh inventory.")
        subprocess.run(["codex", "plugin", "marketplace", "upgrade", "ponytail"], check=True, timeout=180)
        # Recheck the official source after marketplace refresh; never remove the
        # existing plugin or edit hook trust to force an update.
        if not ponytail_config():
            raise ValueError("Ponytail marketplace changed; refusing to install.")
        subprocess.run(["codex", "plugin", "add", "ponytail@ponytail"], check=True, timeout=180)
        after = ponytail_update()
        if after.state != "Current" or not after.eligible:
            raise ValueError("Ponytail update not verified; restart Codex and inspect inventory.")
        print("Ponytail updated. Restart Codex and review /hooks trust.")
    elif key.startswith("skill:") and key[6:] in SKILL_NAMES:
        name = key[6:]
        before = skill_update(name, skill_lock(), kit_tree())
        if before.state == "Current":
            print(name + " is already current.")
            return
        if before.state != "Available" or not before.eligible:
            raise ValueError("Coding Kit skill source/version not verified; refresh inventory.")
        # Official CLI retains existing global placement and lockfile. Explicit
        # skill name + global scope avoids unrelated skills and project updates.
        subprocess.run(["skills", "update", name, "-g", "-y"], check=True, timeout=300, cwd=Path.home())
        after = skill_update(name, skill_lock(), kit_tree())
        if after.state != "Current" or not after.eligible:
            raise ValueError("Skill update not verified; inspect Skills CLI inventory.")
        print(name + " updated and lockfile revision verified.")
    else:
        raise ValueError("Unsupported AI resource.")


def main():
    if len(sys.argv) != 2 or os.geteuid() == 0:
        return 2
    try:
        execute(sys.argv[1])
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Update failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
