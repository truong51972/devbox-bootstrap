"""Resource lifecycle and conservative read-only update discovery."""
from __future__ import annotations

from dataclasses import dataclass, replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from tui.catalog import COMPONENTS, GROUPS, BINS, DEPENDENCIES, inventory
from tui.inventory_detail import APT
from tui.backend import ROOT, build_command
from .agent_setup import ITEMS, EXTENSIONS, selection
from .agents import agent_matrix

NPM = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code",
       "copilot": "@github/copilot", "opencode": "opencode-ai",
       "gemini": "@google/gemini-cli", "skills-cli": "skills"}
RELEASES = {"uv": "astral-sh/uv", "minikube": "kubernetes/minikube", "rtk": "rtk-ai/rtk"}
VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+)(?![\w.+-])")
TTL = 900


@dataclass(frozen=True)
class Resource:
    key: str
    name: str
    group: str
    recommended: bool
    installation: str
    description: str = ""
    update: str = "Unknown"
    installed_version: str = ""
    available_version: str = ""
    manager: str = ""
    path: str = ""
    evidence: str = ""
    integrations: tuple[str, ...] = ()
    can_update: bool = False

    @property
    def status(self):
        if self.installation != "Installed":
            return self.installation
        if self.update == "Available":
            return "Update available"
        if self.update == "Current":
            return "Installed"
        return "Checking" if self.update == "Checking" else "Update unknown"

    @property
    def action(self):
        if self.installation in ("Missing", "Partial", "Disabled"):
            return "Install" if self.installation == "Missing" else "Configure"
        if self.installation == "Installed" and self.update == "Available" and self.can_update:
            return "Update"
        return ""


def command(*argv, timeout=5):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                                stdin=subprocess.DEVNULL, timeout=timeout,
                                env=dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0",
                                         GIT_SSH_COMMAND="ssh -o BatchMode=yes"))
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def version(text):
    match = VERSION.search(text)
    return match.group(1) if match else ""


def newer(current, candidate):
    if not current or not candidate:
        return "Unknown"
    try:
        return "Available" if tuple(map(int, candidate.split("."))) > tuple(map(int, current.split("."))) else "Current"
    except ValueError:
        return "Unknown"


def apt_newer(current, candidate):
    try:
        code = subprocess.run(["dpkg", "--compare-versions", candidate, "gt", current],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=3).returncode
        return "Available" if code == 0 else "Current" if code == 1 else "Unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "Unknown"


def skill_path(key):
    name = key.removeprefix("skill:")
    return Path.home() / ".codex/skills" / name / "SKILL.md"


def local_rows(scope):
    if scope == "ai":
        rows = []
        for item in ITEMS:
            path = shutil.which(item.executable) if item.executable else ""
            if item.key.startswith("skill:"):
                path = str(skill_path(item.key))
                state = "Installed" if Path(path).is_file() else "Missing"
            elif item.key == "ponytail":
                state = "Checking"
            elif item.key == "rtk":
                state = "Checking" if path else "Missing"
            else:
                state = "Installed" if path else "Missing"
            rows.append(Resource(item.key, item.title, item.group, item.default, state,
                                 item.description, path=path or "",
                                 update="Checking" if state == "Installed" else "Unknown"))
        return tuple(rows)
    states = inventory(quick=True)
    names = dict(COMPONENTS)
    return tuple(Resource(key, names[key], group, True, states[key],
                          path=next((p for n in BINS.get(key, ()) if (p := shutil.which(n))), ""),
                          update="Checking" if states[key] == "Installed" else "Unknown")
                 for group, keys in GROUPS for key in keys if key not in EXTENSIONS)


def npm_owned(key, path):
    package = NPM[key]
    prefix = Path.home() / ".local"
    package_root = prefix / "lib/node_modules" / package
    try:
        data = json.loads((package_root / "package.json").read_text())
        binary = Path(path)
        if not binary.is_symlink() or binary != prefix / "bin" / ("skills" if key == "skills-cli" else key):
            return ""
        if not binary.resolve().is_relative_to(package_root.resolve()) or data.get("name") != package:
            return ""
        if key == "skills-cli":
            receipt = Path.home() / ".local/state/devbox-bootstrap/managed/skills-cli"
            if receipt.read_text().strip() != str(binary):
                return ""
        return version(str(data.get("version", "")))
    except (OSError, ValueError, TypeError):
        return ""


def npm_probe(row):
    installed = npm_owned(row.key, row.path)
    if not installed:
        return replace(row, update="Unknown", evidence="External or unverified npm ownership; use original manager.")
    candidate = version(command("npm", "view", NPM[row.key], "version", "--fetch-retries=0", "--fetch-timeout=5000", timeout=7))
    return replace(row, manager="npm (user-local)", installed_version=installed,
                   available_version=candidate, update=newer(installed, candidate), can_update=True)


def apt_probe(row):
    # Check the same packages that the existing upgrade backend manages.
    packages = APT.get(row.key, ())
    if row.key == "docker":
        packages = ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin")
    installed, candidates, states = [], [], []
    owner = command("dpkg-query", "-S", row.path) if row.path else ""
    # An active binary shadowed by another manager must not be auto-updated.
    if not owner or not any(re.search(r"(^|\n)" + re.escape(p) + r"(?::[^:\n]+)?: ", owner) for p in packages):
        return None
    for package in packages:
        current = command("dpkg-query", "-W", "-f=${Version}", package)
        if not current:
            continue
        policy = command("apt-cache", "policy", package)
        match = re.search(r"^\s*Candidate:\s*(\S+)", policy, re.M)
        candidate = match.group(1) if match else ""
        installed.append(package + " " + current)
        candidates.append(package + " " + (candidate or "?"))
        states.append(apt_newer(current, candidate) if candidate and candidate != "(none)" else "Unknown")
    if not states:
        return None
    state = "Available" if "Available" in states else "Unknown" if "Unknown" in states else "Current"
    # Zsh includes git-managed plugins; the APT candidate is only one part.
    if row.key == "zsh" and state == "Current":
        state = "Unknown"
    return replace(row, installed_version=", ".join(installed), available_version=", ".join(candidates),
                   update=state, manager="APT", can_update=True,
                   evidence="Candidate from local APT indexes; execution refreshes indexes.")


def release_probe(row):
    key = row.key
    path = Path(row.path)
    if key == "uv":
        owned = path == Path.home() / ".local/bin/uv" and path.is_file() and not path.is_symlink()
    else:
        receipt = Path.home() / ".local/state/devbox-bootstrap/managed" / (key + ".sha256")
        expected = Path.home() / ".local/bin/rtk" if key == "rtk" else Path("/usr/local/bin") / key
        try:
            owned = path == expected and not path.is_symlink() and not receipt.is_symlink()
            if owned:
                with path.open("rb") as stream:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                owned = digest.hexdigest() == receipt.read_text().strip()
        except OSError:
            owned = False
    if not owned:
        return replace(row, update="Unknown", evidence="External/legacy binary; ownership not verified.")
    args = ("version", "--client", "-o", "json") if key == "kubectl" else ("version", "--short") if key == "minikube" else ("--version",)
    raw = command(row.path, *args)
    if key == "kubectl":
        try:
            raw = json.loads(raw)["clientVersion"]["gitVersion"]
        except (ValueError, KeyError, TypeError):
            raw = ""
    installed = version(raw)
    if key == "kubectl":
        candidate = version(os.environ.get("BOOTSTRAP_KUBECTL_VERSION") or command("curl", "-fsSL", "--max-time", "6", "https://dl.k8s.io/release/stable.txt", timeout=8))
    else:
        raw = command("curl", "-fsSL", "--max-time", "6", "https://api.github.com/repos/" + RELEASES[key] + "/releases/latest", timeout=8)
        try:
            candidate = version(json.loads(raw)["tag_name"])
        except (ValueError, KeyError, TypeError):
            candidate = ""
    return replace(row, manager="Standalone", installed_version=installed, available_version=candidate,
                   update=newer(installed, candidate), can_update=True)


def git_probe(row):
    path = Path.home() / "powerlevel10k"
    origin = command("git", "-C", str(path), "remote", "get-url", "origin")
    allowed = {"https://github.com/romkatv/powerlevel10k", "https://github.com/romkatv/powerlevel10k.git", "git@github.com:romkatv/powerlevel10k.git"}
    if origin not in allowed:
        return replace(row, update="Unknown", evidence="Git origin not verified.")
    current = command("git", "-C", str(path), "rev-parse", "HEAD")
    upstream = command("git", "-C", str(path), "rev-parse", "--abbrev-ref", "@{upstream}")
    if not upstream.startswith("origin/"):
        return replace(row, update="Unknown", evidence="No verified upstream branch.")
    candidate = command("git", "-C", str(path), "ls-remote", "origin", "refs/heads/" + upstream[7:], timeout=8).split()
    latest = candidate[0] if candidate else ""
    # A differing remote revision is not proof of a fast-forward; backend rechecks.
    state = "Current" if current and current == latest else "Unknown"
    return replace(row, manager="Git", installed_version=current[:12], available_version=latest[:12],
                   update=state, evidence="Different revisions require manual fast-forward review." if state == "Unknown" else "")


def probe(row):
    if row.installation != "Installed":
        return row
    if row.key in NPM:
        return npm_probe(row)
    if row.key.startswith("skill:"):
        return replace(row, update="Unknown", manager="Skills CLI", evidence="Codex global skill file exists; source revision not verified. Use Skills update check in Advanced.")
    if row.key == "ponytail":
        return replace(row, update="Unknown", manager="Agent plugin manager", evidence="Update through the verified agent plugin manager.")
    if row.key == "powerlevel10k":
        return git_probe(row)
    apt = apt_probe(row)
    if apt:
        return apt
    if row.key in RELEASES or row.key == "kubectl":
        return release_probe(row)
    return replace(row, update="Unknown", evidence="Original package manager not verified.")


def scan(scope, rows):
    if scope == "ai":
        try:
            matrix = agent_matrix()
            codex = next((r for r in matrix.agents if r.key == "codex"), None)
            enriched = []
            for row in rows:
                if row.key in ("rtk", "ponytail"):
                    statuses = tuple(f"{a.name}: {getattr(a, row.key).state} — {getattr(a, row.key).reason}" for a in matrix.agents)
                    state = getattr(codex, row.key).state if codex else "Unavailable"
                    if row.key == "rtk" and matrix.binary.state != "Installed":
                        state = matrix.binary.state
                    if state == "Unavailable":
                        state = "Missing" if not codex or codex.cli == "Unavailable" else "Unverified"
                    row = replace(row, installation=state, integrations=statuses)
                enriched.append(row)
            rows = tuple(enriched)
        except (OSError, ValueError, RuntimeError):
            rows = tuple(replace(r, installation="Unverified") if r.installation == "Checking" else r for r in rows)
    with ThreadPoolExecutor(max_workers=4) as pool:
        return tuple(pool.map(probe, rows))


@dataclass(frozen=True)
class Operation:
    verb: str
    key: str
    name: str
    command: tuple[str, ...] = ()


def plan(scope, rows, keys):
    by_key = {r.key: r for r in rows}
    if not keys or set(keys) - set(by_key):
        raise ValueError("Select valid resources.")
    selected = set(keys)
    if scope == "development":
        for key in tuple(selected):
            if by_key[key].action in ("Install", "Configure"):
                selected.update(dep for dep in DEPENDENCIES.get(key, ()) if by_key[dep].installation == "Missing")
    else:
        installs = [key for key in selected if by_key[key].action in ("Install", "Configure")]
        if installs:
            selected.update(key for key in selection(installs) if by_key[key].installation in ("Missing", "Partial", "Disabled"))
    result = []
    for row in rows:
        if row.key not in selected:
            continue
        verb = row.action
        if not verb:
            result.append(Operation("Skip", row.key, row.name))
        elif scope == "development":
            args = build_command("upgrade" if verb == "Update" else "install", [row.key])
            result.append(Operation(verb, row.key, row.name, tuple(args)))
        elif verb == "Update":
            if row.key in NPM and row.key != "skills-cli":
                args = ("bash", str(ROOT / "utils/agent-update.sh"), row.key)
            else:
                args = tuple(build_command("upgrade", [row.key]))
            result.append(Operation(verb, row.key, row.name, args))
        else:
            result.append(Operation(verb, row.key, row.name, ("bash", str(ROOT / "utils/ai-setup.sh"), "--yes", row.key)))
    # Install dependencies first, and update only after installations are complete.
    return tuple(sorted(result, key=lambda op: {"Install": 0, "Configure": 1, "Update": 2, "Skip": 3}[op.verb]))
