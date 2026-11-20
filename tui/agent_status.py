"""Read-only Ponytail plugin inventory adapters for supported coding-agent CLIs.

Discovery only inspects PATH; CLI probes are deliberately synchronous so they
can be executed in asyncio.to_thread, never on the TUI's event loop. No
installation receipts are required: manually installed plugins are visible.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

AGENTS = ("claude", "codex", "copilot", "opencode", "gemini")
LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "copilot": "Copilot CLI",
    "opencode": "OpenCode",
    "gemini": "Gemini CLI",
}
_COMMANDS = {
    "claude": ("claude", "plugin", "list", "--json"),
    "codex": ("codex", "plugin", "list", "--json"),
    "copilot": ("copilot", "plugin", "list", "--json"),
    "opencode": ("opencode", "plugin", "list"),
    "gemini": ("gemini", "extensions", "list"),
}
_PONYTAIL = re.compile(r"(?<![a-z0-9_-])ponytail(?![a-z0-9_-])", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def discover_agents() -> dict[str, str]:
    """Cheap, non-blocking state for *all* supported agents, with or without receipts."""
    return {
        agent: ("Checking" if shutil.which(agent) else "Unavailable")
        for agent in AGENTS
    }


def _is_ponytail(row: dict) -> bool:
    return any(
        isinstance(row.get(key), str) and _PONYTAIL.search(row[key])
        for key in ("id", "pluginId", "name", "package", "plugin_id")
    )


def _from_json(agent: str, output: str) -> str:
    try:
        payload = json.loads(output)
    except (ValueError, TypeError):
        return "Unverified"
    if agent == "codex":
        # Codex lists marketplace-available plugins separately from installations.
        rows = payload.get("installed") if isinstance(payload, dict) else None
    else:
        rows = payload if isinstance(payload, list) else (
            payload.get("installed", payload.get("plugins"))
            if isinstance(payload, dict) else None
        )
    if not isinstance(rows, list):
        return "Unverified"
    matches = [row for row in rows if isinstance(row, dict) and _is_ponytail(row)]
    if not matches:
        return "Missing"
    if any(row.get("errors") or row.get("errorDetails") for row in matches):
        return "Unverified"
    if any(row.get("enabled") is True and row.get("installed") is not False
           for row in matches):
        return "Installed"
    if any(row.get("enabled") is False for row in matches):
        return "Disabled"
    if any(row.get("installed") is False for row in matches):
        return "Missing"
    # Installed-only inventories may omit the enabled field.
    return "Installed"


def _from_text(output: str, *, gemini: bool = False) -> str:
    text = _ANSI.sub("", output)
    lines = text.splitlines()
    matches = [
        i for i, line in enumerate(lines)
        if _PONYTAIL.search(line)
        and not line.strip().lower().startswith(("path:", "source:", "id:"))
    ]
    if not matches:
        return "Missing"
    if gemini:
        # Gemini prints enable flags below the extension name. Any enabled
        # scope makes it available; both false indicates disabled.
        for index in matches:
            flags = []
            for line in lines[index:index + 12]:
                result = re.match(
                    r"\s*Enabled\s*\((User|Workspace)\)\s*:\s*(true|false)",
                    line, re.I,
                )
                if result:
                    flags.append(result.group(2).lower() == "true")
            if any(flags):
                return "Installed"
            if flags:
                return "Disabled"
        return "Unverified"
    entries = [lines[i] for i in matches]
    if any(re.search(r"\b(failed|error|not loaded)\b", line, re.I)
           for line in entries):
        return "Unverified"
    if any(re.search(r"\b(disabled|inactive|not enabled)\b", line, re.I)
           for line in entries):
        return "Disabled"
    return "Installed"


def probe_agent(agent: str) -> str:
    """Read-only bounded CLI check. Never equate a failed query with Missing."""
    if agent not in _COMMANDS or not shutil.which(agent):
        return "Unavailable"
    try:
        result = subprocess.run(
            _COMMANDS[agent], check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=2,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return "Unverified"
    if result.returncode != 0:
        return "Unverified"
    if agent in ("claude", "codex", "copilot"):
        return _from_json(agent, result.stdout)
    return _from_text(result.stdout, gemini=agent == "gemini")


def summary(statuses: dict[str, str]) -> str:
    """Aggregate installed CLIs only; absent CLIs must not affect the verdict."""
    values = [v for v in statuses.values() if v != "Unavailable"]
    if not values:
        return "Missing"
    if "Checking" in values:
        return "Checking"
    if all(v == "Installed" for v in values):
        return "Installed"
    if any(v == "Installed" for v in values):
        return "Partial"
    if "Unverified" in values:
        return "Unverified"
    if "Disabled" in values:
        return "Disabled"
    return "Missing"
