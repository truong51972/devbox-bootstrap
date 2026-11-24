"""Read-only RTK binary and user-scoped integration inventory."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from tui.agent_status import AGENTS, LABELS, PluginStatus, discover_agents, probe_agent_detail

_TIMEOUT = 5


@dataclass(frozen=True)
class RtkInventory:
    binary: PluginStatus
    agents: dict[str, PluginStatus]

    @property
    def state(self) -> str:
        if self.binary.state != "Installed":
            return self.binary.state
        states = [item.state for item in self.agents.values()
                  if item.state != "Unavailable"]
        if not states or all(state == "Installed" for state in states):
            return "Installed"
        if "Checking" in states:
            return "Checking"
        if "Unverified" in states and all(state == "Unverified" for state in states):
            return "Unverified"
        return "Partial"


def executable_path() -> str | None:
    found = shutil.which("rtk")
    if found:
        return found
    for folder in (".local/bin", ".cargo/bin"):
        path = Path.home() / folder / "rtk"
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def binary_status() -> PluginStatus:
    path = executable_path()
    if not path:
        return PluginStatus("rtk", "Missing", "PATH", "Binary not found")
    try:
        result = subprocess.run([path, "gain"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                stdin=subprocess.DEVNULL, timeout=_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return PluginStatus("rtk", "Unverified", "binary", "Identity check timed out")
    except OSError:
        return PluginStatus("rtk", "Unverified", "binary", "Cannot execute binary")
    if result.returncode != 0:
        return PluginStatus("rtk", "Unverified", "binary",
                            f"rtk gain failed (exit {result.returncode})")
    return PluginStatus("rtk", "Installed", "binary", path)


def _home(env: str, default: str) -> Path:
    return Path(os.environ.get(env) or Path.home() / default).expanduser()


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None


def _native_or_wrapper(command: str, agent: str, root: Path) -> str | None:
    """Recognize native RTK commands and existing upstream shell wrappers."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "Unverified" if "rtk" in command else None
    if not tokens:
        return None
    # Only accept a command invocation, not a mention in echo/printf/etc.
    if Path(tokens[0]).name in ("bash", "sh", "zsh"):
        tokens = tokens[1:]
    if not tokens:
        return None
    for index, token in enumerate(tokens[:1]):
        name = Path(token).name
        if name in ("rtk", "rtk.exe") and tokens[index + 1:index + 3] == ["hook", agent]:
            return "Installed"
        if name in ("rtk-rewrite.sh", "rtk-hook-gemini.sh", "rtk-hook-codex.sh",
                    "rtk-hook-copilot.sh"):
            target = Path(os.path.expandvars(token)).expanduser()
            if not target.is_absolute():
                target = root / target
            try:
                source = _read(target)
            except (OSError, UnicodeError):
                return "Unverified"
            if source and re.search(r"\brtk\b", source):
                return "Installed"
            return "Unverified"
    return None


def _hook_status(path: Path, event: str, agent: str, root: Path) -> str | None:
    raw = _read(path)
    if raw is None:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return "Unverified"
    if payload.get("disableAllHooks") is True:
        return "Disabled"
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        return "Unverified"
    rows = [row for key, value in hooks.items() if key.lower() == event.lower()
            for row in (value if isinstance(value, list) else [])]
    states = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested = row.get("hooks", [row])
        if not isinstance(nested, list):
            continue
        for hook in nested:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command", hook.get("bash"))
            if not isinstance(command, str):
                continue
            state = _native_or_wrapper(command, agent, root)
            if state:
                if row.get("enabled") is False or hook.get("enabled") is False:
                    state = "Disabled"
                states.append(state)
    for state in ("Installed", "Unverified", "Disabled"):
        if state in states:
            return state
    return None


def integration_status(agent: str, available: str) -> PluginStatus:
    if available == "Unavailable":
        return PluginStatus(agent, "Unavailable", "PATH", "CLI not installed")
    try:
        if agent == "opencode":
            root = _home("XDG_CONFIG_HOME", ".config") / "opencode"
            root = Path(os.environ.get("OPENCODE_CONFIG_DIR") or root).expanduser()
            paths = [root / "plugins" / "rtk.ts", root / "plugin" / "rtk.ts"]
            for path in paths:
                source = _read(path)
                if source is not None:
                    if (re.search(r"\b(?:tool\.execute\.before|execute\.before)\b", source)
                            and re.search(r"\brtk\b", source)):
                        return PluginStatus(agent, "Installed", "local plugin", "Plugin configured")
                    return PluginStatus(agent, "Unverified", "local plugin", "Unknown plugin format")
            return PluginStatus(agent, "Missing", "local plugin", "Plugin not configured")

        root = {
            "claude": _home("CLAUDE_CONFIG_DIR", ".claude"),
            "codex": _home("CODEX_HOME", ".codex"),
            "copilot": _home("COPILOT_HOME", ".copilot"),
            "gemini": _home("GEMINI_CLI_HOME", ".gemini"),
        }[agent]
        if agent == "copilot":
            paths = sorted((root / "hooks").glob("*.json"))
        elif agent == "codex":
            paths = [root / "hooks.json"]
        else:
            paths = [root / "settings.json"]
        event = "BeforeTool" if agent == "gemini" else "PreToolUse"
        states = [_hook_status(path, event, agent, root) for path in paths]
        if "Installed" in states:
            return PluginStatus(agent, "Installed", "local config", "Hook configured")
        if "Unverified" in states:
            return PluginStatus(agent, "Unverified", "local config", "Hook could not be verified")
        if "Disabled" in states:
            return PluginStatus(agent, "Disabled", "local config", "Hooks disabled")
        # Older Codex releases installed awareness instructions rather than hooks.
        if agent == "codex":
            instructions = _read(root / "AGENTS.md") or ""
            awareness = _read(root / "RTK.md")
            if awareness and re.search(r"(?im)^\s*@(?:\./)?RTK\.md\s*$", instructions):
                return PluginStatus(agent, "Installed", "instructions", "Rules only; no automatic hook")
        return PluginStatus(agent, "Missing", "local config", "Hook not configured")
    except (OSError, ValueError, UnicodeError, KeyError):
        return PluginStatus(agent, "Unverified", "local config", "Cannot read integration config")


def inspect_rtk(availability: dict[str, str] | None = None) -> RtkInventory:
    discovered = discover_agents() if availability is None else availability
    binary = binary_status()
    agents = {agent: integration_status(agent, discovered.get(agent, "Unavailable"))
              for agent in AGENTS}
    return RtkInventory(binary, agents)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agents", nargs="*")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if any(agent not in AGENTS for agent in args.agents):
        parser.error("Unsupported agent")
    availability = discover_agents()
    if availability.get("copilot") == "Checking" and (not args.agents or "copilot" in args.agents):
        if probe_agent_detail("copilot").state == "Unavailable":
            availability["copilot"] = "Unavailable"
    inventory = inspect_rtk(availability)
    print(f"RTK binary: {inventory.binary.state} ({inventory.binary.reason})")
    targets = args.agents if args.verify else (args.agents or list(AGENTS))
    for agent in targets:
        status = inventory.agents[agent]
        print(f"RTK / {LABELS[agent]}: {status.state} ({status.reason})")
    if args.verify:
        return int(inventory.binary.state != "Installed" or
                   any(inventory.agents[agent].state != "Installed" for agent in targets))
    return int(inventory.binary.state == "Unverified")


if __name__ == "__main__":
    raise SystemExit(main())
