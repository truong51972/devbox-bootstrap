"""Read-only Ponytail status probes for integrations managed by coding agents.

Receipts identify which agent Devbox installed for; they are *not* used to
claim that the plugin is active. Only successful read-only agent inventory
commands can promote an integration to Installed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess

AGENTS = ("claude", "codex", "copilot", "opencode", "gemini")
RECEIPT_DIR = Path.home() / ".local/state/devbox-bootstrap/agent-extensions"
_COMMANDS = {
    "claude": ("claude", "plugin", "list", "--json"),
    "codex": ("codex", "plugin", "list", "--json"),
    "copilot": ("copilot", "plugin", "list", "--json"),
    "opencode": ("opencode", "plugin", "list"),
    "gemini": ("gemini", "extensions", "list"),
}
# Match Ponytail itself, not an unrelated "ponytail-utils" plugin.
_PONYTAIL = re.compile(r"(?<![a-z0-9_-])ponytail(?![a-z0-9_-])", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


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
        # Codex also returns *available* plugins: ignore those.
        rows = payload.get("installed") if isinstance(payload, dict) else None
    else:
        rows = payload if isinstance(payload, list) else (
            payload.get("plugins") if isinstance(payload, dict) else None
        )
    if not isinstance(rows, list):
        return "Unverified"
    matches = [row for row in rows if isinstance(row, dict) and _is_ponytail(row)]
    if any(row.get("enabled") is not False and row.get("installed") is not False
           for row in matches):
        return "Installed"
    if matches:
        return "Disabled" if any(row.get("enabled") is False for row in matches) else "Missing"
    return "Missing"


def _from_text(output: str) -> str:
    text = _ANSI.sub("", output)
    lines = [line.strip() for line in text.splitlines() if _PONYTAIL.search(line)]
    if not lines:
        return "Missing"
    # Only consider explicit per-plugin entries, not arbitrary error messages.
    if any(re.search(r"\b(disabled|inactive|not enabled)\b", line, re.I)
           for line in lines):
        return "Disabled"
    return "Installed"


def probe_agent(agent: str) -> str:
    """Return Installed/Disabled/Missing/Unverified; never mutate agent config."""
    if agent not in _COMMANDS or not shutil.which(agent):
        return "Unverified"
    try:
        result = subprocess.run(
            _COMMANDS[agent], check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=2,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Unverified"
    if result.returncode != 0:
        return "Unverified"
    return (_from_json(agent, result.stdout)
            if agent in ("claude", "codex", "copilot")
            else _from_text(result.stdout))


def probe_ponytail(receipt_dir: Path | None = None) -> dict[str, str]:
    """Probe only installed targets recorded by Devbox, in parallel.

    Bound the startup delay to approximately one subprocess timeout even
    when the user has several coding agents configured.
    """
    base = RECEIPT_DIR if receipt_dir is None else receipt_dir
    targets = [
        agent for agent in AGENTS if (base / f"ponytail-{agent}").is_file()
    ]
    if not targets:
        return {}
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        return dict(zip(targets, pool.map(probe_agent, targets)))


def summary(statuses: dict[str, str]) -> str:
    if not statuses:
        return "Missing"
    values = list(statuses.values())
    if all(v == "Installed" for v in values):
        return "Installed"
    if all(v == "Missing" for v in values):
        return "Missing"
    if any(v == "Installed" for v in values):
        return "Partial"
    if any(v == "Unverified" for v in values):
        return "Unverified"
    if any(v == "Disabled" for v in values):
        return "Disabled"
    return "Unverified"
