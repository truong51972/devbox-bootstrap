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
import shlex
import subprocess
import sys

from tui.catalog import COMPONENTS, GROUPS, BINS, DEPENDENCIES, inventory
from tui.inventory_detail import APT
from tui.backend import ROOT, build_command
from .agent_setup import ITEMS, EXTENSIONS, selection
from .agents import agent_matrix
from . import ai_resource_updates as ai_updates
from . import binary_adoption
from . import installed_managers

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
    ownership: str = "Unverified"
    can_adopt: bool = False
    update_command: tuple[str, ...] = ()

    @property
    def status(self):
        if self.installation != "Installed":
            return self.installation
        if self.update == "Available":
            return "Update available" if self.can_update or self.can_adopt else "Update blocked"
        if self.update == "Current":
            return "Installed"
        if self.update == "Failed":
            return "Check failed"
        return "Checking" if self.update == "Checking" else "Update unknown"

    @property
    def action(self):
        if self.installation in ("Missing", "Partial", "Disabled"):
            return "Install" if self.installation == "Missing" else "Configure"
        if self.installation == "Installed" and self.update != "Checking" and (self.can_update or self.can_adopt):
            return "Update"
        return ""

    @property
    def bulk_update(self):
        return self.action == "Update" and self.update in ("Available", "Unknown", "Failed")


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
    return ai_updates.skill_path(name)


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


def manager_args(row, route):
    return ("bash", str(ROOT / "utils/installed-update.sh"), sys.executable,
            row.key, row.path, route.kind, route.prefix) if route else ()


def npm_probe(row):
    route = installed_managers.detect(row.key, row.path)
    installed = (route.version if route else "") or (version(command(row.path, "--version")) if row.path else "")
    candidate = version(command("npm", "view", NPM[row.key], "version", "--fetch-retries=0", "--fetch-timeout=5000", timeout=7))
    return replace(row, manager=route.label if route else "Manager unrecognized",
                   ownership="Verified" if route else "Unverified", installed_version=installed,
                   available_version=candidate, update=newer(installed, candidate) if candidate else "Failed",
                   can_update=bool(route), update_command=manager_args(row, route),
                   evidence=("Update through original manager; revalidated before execution." if route else
                             "Installed, but no supported writable update provider; active executable preserved.")
                   + (" Upstream query failed; verified providers can retry." if not candidate else ""))


def package_owner(path, packages):
    """Resolve user-local aliases and merged-/usr paths before querying dpkg."""
    if not path:
        return False
    try:
        resolved = str(Path(path).resolve())
    except (OSError, RuntimeError):
        return False
    paths = list(dict.fromkeys((path, resolved)))
    if resolved.startswith("/usr/"):
        paths.append(resolved[4:])
    elif resolved.startswith(("/bin/", "/sbin/", "/lib/")):
        paths.append("/usr" + resolved)
    for candidate in dict.fromkeys(paths):
        owner = command("dpkg-query", "-S", candidate)
        if any(re.search(r"(^|\n)" + re.escape(pkg) + r"(?::[^:\n]+)?: ", owner)
               for pkg in packages):
            return True
    return False


def apt_probe(row):
    packages = APT.get(row.key, ())
    if not packages:
        return None
    if row.key == "docker":
        packages = ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin")
    if row.key == "bat-fd":
        targets = [(row.path, ("bat",)),
                   (shutil.which("fd") or shutil.which("fdfind"), ("fd-find",))]
    else:
        targets = [(row.path, packages)]
    if not all(package_owner(path, owners) for path, owners in targets):
        return None
    installed, candidates, states = [], [], []
    for package in packages:
        raw = command("dpkg-query", "-W", "-f=${Status}\\t${Version}", package)
        status, sep, current = raw.partition("\t")
        if not sep or status != "install ok installed" or not current:
            continue
        policy = command("apt-cache", "policy", package)
        match = re.search(r"^\s*Candidate:\s*(\S+)", policy, re.M)
        candidate = match.group(1) if match else ""
        installed.append(package + " " + current)
        candidates.append(package + " " + (candidate or "?"))
        states.append(apt_newer(current, candidate) if candidate and candidate != "(none)" else "Failed")
    if not states:
        return None
    state = aggregate(states)
    return replace(row, installed_version=", ".join(installed), available_version=", ".join(candidates),
                   update=state, manager="APT", can_update=True, ownership="Verified",
                   evidence="Candidate from local APT indexes; execution refreshes indexes."
                   + (" One or more package candidates could not be checked." if "Failed" in states else ""))


def aggregate(states):
    if "Available" in states:
        return "Available"
    if "Failed" in states:
        return "Failed"
    if "Unknown" in states or not states:
        return "Unknown"
    return "Current"


def binary_version(key, path):
    if not path:
        return ""
    args = ("version", "--client", "-o", "json") if key == "kubectl" else ("version", "--short") if key == "minikube" else ("--version",)
    raw = command(path, *args)
    if key == "kubectl":
        try:
            raw = json.loads(raw)["clientVersion"]["gitVersion"]
        except (ValueError, KeyError, TypeError):
            return ""
    return version(raw)


def release_probe(row):
    key = row.key
    path = Path(row.path)
    if key == "uv":
        owned = path == Path.home() / ".local/bin/uv" and path.is_file() and not path.is_symlink()
    else:
        receipt = Path.home() / ".local/state/devbox-bootstrap/managed" / (key + ".sha256")
        expected = Path.home() / ".local/bin/rtk" if key == "rtk" else Path("/usr/local/bin") / key
        try:
            owned = path == expected and path.is_file() and not path.is_symlink() and not receipt.is_symlink() and receipt.stat().st_size <= 256
            if owned:
                with path.open("rb") as stream:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                owned = digest.hexdigest() == receipt.read_text().strip()
        except OSError:
            owned = False
    # Version discovery is read-only and independent of permission to mutate.
    installed = binary_version(key, row.path)
    if key == "kubectl":
        candidate = version(os.environ.get("BOOTSTRAP_KUBECTL_VERSION") or command("curl", "-fsSL", "--max-time", "6", "https://dl.k8s.io/release/stable.txt", timeout=8))
    else:
        raw = command("curl", "-fsSL", "--max-time", "6", "https://api.github.com/repos/" + RELEASES[key] + "/releases/latest", timeout=8)
        try:
            candidate = version(json.loads(raw)["tag_name"])
        except (ValueError, KeyError, TypeError):
            candidate = ""
    evidence = "Verified standalone installation." if owned else "External/legacy binary; automatic replacement blocked."
    adopt = not owned and bool(installed) and binary_adoption.eligible(key, row.path)
    if adopt:
        evidence += " M verifies official release checksum and adopts without replacing the binary."
    if not candidate:
        evidence += " Upstream version query failed or returned invalid metadata."
    if not installed:
        evidence += " Installed version could not be parsed."
    route = installed_managers.detect(key, row.path) if key in ("uv", "rtk") and not owned else None
    if route:
        evidence = "Update through " + route.label + "; revalidated before execution."
    return replace(row, manager=route.label if route else "Standalone", installed_version=installed, available_version=candidate,
                   update=newer(installed, candidate) if candidate else "Failed", can_update=owned or bool(route),
                   ownership="Verified" if owned or route else "Unmanaged", can_adopt=adopt, evidence=evidence,
                   update_command=manager_args(row, route))


def git_checkout(path, repo):
    """Check official origin and remote branch without modifying the checkout."""
    label = repo.rsplit("/", 1)[-1]
    if not (path / ".git").exists():
        return ("Unknown", "", "", label + ": repository missing", False)
    origin = command("git", "-C", str(path), "remote", "get-url", "origin")
    allowed = {"https://github.com/" + repo, "https://github.com/" + repo + ".git",
               "git@github.com:" + repo + ".git"}
    if origin not in allowed:
        return ("Unknown", "", "", label + ": custom origin", False)
    current = command("git", "-C", str(path), "rev-parse", "HEAD")
    upstream = command("git", "-C", str(path), "rev-parse", "--abbrev-ref", "@{upstream}")
    if not upstream.startswith("origin/") or not re.fullmatch(r"[0-9a-f]{40}", current):
        return ("Unknown", current[:12], "", label + ": no verified upstream", False)
    result = command("git", "-C", str(path), "ls-remote", "origin", "refs/heads/" + upstream[7:], timeout=8).split()
    latest = result[0] if result else ""
    if not re.fullmatch(r"[0-9a-f]{40}", latest):
        return ("Failed", current[:12], "", label + ": remote query failed", False)
    # porcelain output can be empty on success or failure; check exit separately.
    try:
        check = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5, check=False)
        clean = check.returncode == 0 and not check.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        clean = False
    if current == latest:
        return ("Current", current[:12], latest[:12], label + (": current" if clean else ": local changes"), clean)
    raw = command("curl", "-fsSL", "--max-time", "6",
                  "https://api.github.com/repos/" + repo + "/compare/" + current + "..." + latest, timeout=8)
    try:
        comparison = json.loads(raw).get("status")
    except (ValueError, AttributeError):
        comparison = None
    if comparison == "ahead":
        return ("Available", current[:12], latest[:12], label + (": fast-forward available" if clean else ": local changes; manual update"), clean)
    if comparison == "behind":
        return ("Current", current[:12], latest[:12], label + ": local revision ahead; preserved", False)
    return ("Unknown" if comparison == "diverged" else "Failed", current[:12], latest[:12],
            label + ": " + ("diverged history" if comparison == "diverged" else "ancestry not verified"), False)


def git_probe(row):
    state, current, candidate, evidence, safe = git_checkout(Path.home() / "powerlevel10k", "romkatv/powerlevel10k")
    return replace(row, manager="Git", installed_version=current, available_version=candidate,
                   update=state, evidence=evidence, can_update=safe,
                   ownership="Verified" if safe else "Unverified")


def zsh_probe(row):
    apt = apt_probe(row)
    home = Path.home()
    custom = Path(os.environ.get("ZSH_CUSTOM") or home / ".oh-my-zsh/custom")
    parts = [
        git_checkout(home / ".oh-my-zsh", "ohmyzsh/ohmyzsh"),
        git_checkout(custom / "plugins/zsh-autosuggestions", "zsh-users/zsh-autosuggestions"),
    ]
    states = ([apt.update] if apt else ["Unknown"]) + [part[0] for part in parts]
    # Existing backend skips dirty/custom Git repositories and only updates APT.
    # Require verified APT ownership and safe git state for automatic batch updates.
    safe = bool(apt and apt.can_update and all(part[3].endswith((": current", ": fast-forward available")) and part[4] for part in parts))
    return replace(row, manager="APT + Git", installed_version="; ".join(([apt.installed_version] if apt else ["zsh: unknown"]) + [part[1] or "?" for part in parts]),
                   available_version="; ".join(([apt.available_version] if apt else ["zsh: unknown"]) + [part[2] or "?" for part in parts]),
                   update=aggregate(states), can_update=safe, ownership="Verified" if safe else "Unverified",
                   evidence="; ".join(([apt.evidence] if apt else ["Zsh APT ownership unverified"]) + [part[3] for part in parts]))


def probe(row):
    if row.installation != "Installed":
        return row
    if row.key in NPM:
        return npm_probe(row)
    if row.key.startswith("skill:"):
        return row  # Enriched in scan using one shared upstream tree request.
    if row.key == "ponytail":
        info = ai_updates.ponytail_update()
        return replace(row, update=info.state, manager="Codex plugin manager",
                       installed_version=info.installed, available_version=info.candidate,
                       evidence=info.reason, can_update=info.eligible,
                       ownership="Verified" if info.eligible else "Unverified")
    if row.key == "powerlevel10k":
        return git_probe(row)
    if row.key == "zsh":
        return zsh_probe(row)
    apt = apt_probe(row)
    if apt:
        return apt
    if row.key in RELEASES or row.key == "kubectl":
        return release_probe(row)
    return replace(row, update="Unknown", installed_version=version(command(row.path, "--version")) if row.path else "",
                   evidence="Original package manager not verified; automatic replacement blocked.")


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
                    if row.key == "rtk":
                        # Binary lifecycle is independent of per-agent hook configuration.
                        state = matrix.binary.state
                    if state == "Unavailable":
                        state = "Missing" if not codex or codex.cli == "Unavailable" else "Unverified"
                    row = replace(row, installation=state, integrations=statuses)
                enriched.append(row)
            rows = tuple(enriched)
        except (OSError, ValueError, RuntimeError):
            rows = tuple(replace(r, installation="Unverified") if r.installation == "Checking" else r for r in rows)
    if scope == "ai":
        entries = ai_updates.skill_lock()
        tree = ai_updates.kit_tree() if any(r.key.startswith("skill:") and r.installation == "Installed" for r in rows) else {}
        enriched = []
        for row in rows:
            if row.key.startswith("skill:") and row.installation == "Installed":
                info = ai_updates.skill_update(row.key[6:], entries, tree)
                row = replace(row, update=info.state, manager="Skills CLI (global)",
                              installed_version=info.installed, available_version=info.candidate,
                              evidence=info.reason, can_update=info.eligible,
                              ownership="Verified" if info.eligible else "Unverified")
            enriched.append(row)
        rows = tuple(enriched)
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
        elif verb == "Update" and row.update_command:
            result.append(Operation(verb, row.key, row.name, row.update_command))
        elif verb == "Update" and row.can_adopt and not row.can_update:
            adopt = ("bash", str(ROOT / "utils/adopt-binary.sh"), sys.executable, row.key, row.installed_version)
            args = ("bash", "-c", shlex.join(adopt) + " && " + shlex.join(build_command("upgrade", [row.key])))
            result.append(Operation(verb, row.key, row.name + " (verify/adopt first)", args))
        elif scope == "development":
            args = build_command("upgrade" if verb == "Update" else "install", [row.key])
            result.append(Operation(verb, row.key, row.name, tuple(args)))
        elif verb == "Update":
            if row.key == "ponytail" or row.key.startswith("skill:"):
                args = ("bash", str(ROOT / "utils/ai-resource-update.sh"), sys.executable, row.key)
            elif row.key in NPM and row.key != "skills-cli":
                args = ("bash", str(ROOT / "utils/agent-update.sh"), row.key)
            else:
                args = tuple(build_command("upgrade", [row.key]))
            result.append(Operation(verb, row.key, row.name, args))
        else:
            result.append(Operation(verb, row.key, row.name, ("bash", str(ROOT / "utils/ai-setup.sh"), "--yes", row.key)))
    # Install dependencies first, and update only after installations are complete.
    return tuple(sorted(result, key=lambda op: {"Install": 0, "Configure": 1, "Update": 2, "Skip": 3}[op.verb]))
