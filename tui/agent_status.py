"""Read-only Ponytail inventory, shared by TUI and shell diagnostics."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

try:
    import tomllib
except ImportError:  # Python 3.10 (Ubuntu 22.04)
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

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
_TIMEOUT = 6
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ID = re.compile(r"(?:ponytail(?:@ponytail)?|@dietrichgebert/ponytail(?:@[^\s]+)?)", re.I)
_ENTRY = re.compile(
    r"^\s*(?:[✓✔✗✘●○•*-]\s+)?(?P<name>@?[\w./-]+(?:@[\w.^~+-]+)?)"
    r"(?:\s+\([^)]*\)|\s+v?\d[\w.+-]*|\s+\[(?:enabled|disabled)\])?\s*$",
    re.I,
)
_FLAGS = re.compile(r"\s*Enabled\s*\((User|Workspace)\)\s*:\s*(true|false)\s*$", re.I)
_EMPTY = re.compile(r"(?:no (?:installed )?(?:plugins|extensions)(?: (?:installed|found|configured|available))?\.?|(?:plugins|extensions):\s*(?:none|\(none\)))", re.I)
_HEADER = re.compile(r"(?:installed\s+)?(?:plugins|extensions)\s*:", re.I)


@dataclass(frozen=True)
class PluginStatus:
    agent: str
    state: str
    source: str
    reason: str
    version: str | None = None
    scope: str | None = None


def discover_agents() -> dict[str, str]:
    return {agent: "Checking" if shutil.which(agent) else "Unavailable"
            for agent in AGENTS}


def _identity(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value.strip()) is not None


def _is_ponytail(row: dict) -> bool:
    return any(_identity(row.get(key)) for key in
               ("id", "pluginId", "name", "package", "plugin_id"))


def _from_json(agent: str, output: str) -> str:
    try:
        payload = json.loads(output)
    except (ValueError, TypeError):
        return "Unverified"
    if isinstance(payload, dict) and (payload.get("error") or payload.get("errors")):
        return "Unverified"
    if agent == "codex":
        rows = payload.get("installed") if isinstance(payload, dict) else None
    else:
        rows = payload if isinstance(payload, list) else (
            payload.get("installed", payload.get("plugins"))
            if isinstance(payload, dict) else None
        )
    if not isinstance(rows, list):
        return "Unverified"
    # Unknown or malformed rows cannot establish a negative inventory.
    if any(not isinstance(row, dict) or not any(
        isinstance(row.get(key), str) and row[key].strip()
        for key in ("id", "pluginId", "name", "package", "plugin_id")
    ) for row in rows):
        return "Unverified"
    matches = [row for row in rows if _is_ponytail(row)]
    if not matches:
        return "Missing"
    states = []
    for row in matches:
        if row.get("errors") or row.get("errorDetails") or row.get("error"):
            states.append("Unverified")
        elif any(key in row and not isinstance(row[key], bool)
                 for key in ("enabled", "installed")):
            states.append("Unverified")
        elif row.get("installed") is False:
            states.append("Missing")
        elif row.get("enabled") is False:
            states.append("Disabled")
        else:
            # Recognized installed-only inventory may omit enabled.
            states.append("Installed")
    for state in ("Installed", "Unverified", "Disabled", "Missing"):
        if state in states:
            return state
    return "Unverified"


def _from_text(output: str, *, gemini: bool = False) -> str:
    lines = _ANSI.sub("", output).splitlines()
    records: list[tuple[str, str, list[str]]] = []
    current = None
    recognized = False
    unknown = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _EMPTY.fullmatch(stripped) or _HEADER.fullmatch(stripped):
            recognized = True
            current = None
            continue
        # Metadata belongs to the preceding record, not a fixed line window.
        if re.match(r"^\s*(?:Path|Source|ID|Version|Type|Release tag|Auto.update|Enabled(?:\s*\([^)]*\))?|Extension ID)\s*:", line, re.I):
            if current is not None:
                current[2].append(line)
            else:
                unknown = True
            continue
        match = _ENTRY.fullmatch(line)
        if match and (re.search(r"\s|\(", stripped) or _identity(match["name"])):
            current = (match["name"], stripped, [])
            records.append(current)
            recognized = True
        else:
            current = None
            unknown = True
    matches = [(header, metadata) for name, header, metadata in records
               if _identity(name)]
    if not matches:
        return "Missing" if recognized and not unknown else "Unverified"
    states = []
    for header, metadata in matches:
        if re.search(r"\b(failed|error|not loaded)\b", header, re.I):
            states.append("Unverified")
        elif gemini:
            flags = {m[1].lower(): m[2].lower() == "true"
                     for line in metadata if (m := _FLAGS.fullmatch(line))}
            states.append("Installed" if any(flags.values()) else
                          "Disabled" if flags else "Unverified")
        elif re.search(r"\b(disabled|inactive|not enabled)\b", header, re.I):
            states.append("Disabled")
        else:
            states.append("Installed")
    for state in ("Installed", "Unverified", "Disabled"):
        if state in states:
            return state
    return "Unverified"


def _jsonc(text: str) -> object:
    # Strip comments and trailing commas without altering quoted strings.
    token = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
    clean = token.sub(lambda m: m[0] if m[0].startswith('"') else " ", text)
    trailing = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')
    return json.loads(trailing.sub(lambda m: m[0] if m[0].startswith('"') else "", clean))


def _opencode_config() -> PluginStatus | None:
    """Positive evidence only for legacy user config; never infer absence."""
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "opencode"
    paths = [root / "opencode.json", root / "opencode.jsonc"]
    if os.environ.get("OPENCODE_CONFIG"):
        paths.append(Path(os.environ["OPENCODE_CONFIG"]).expanduser())
    for path in paths:
        try:
            payload = _jsonc(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in ("plugin", "plugins"):
            entries = payload.get(key)
            if isinstance(entries, list) and any(
                isinstance(entry, str) and
                re.fullmatch(r"@dietrichgebert/ponytail(?:@[^\s]+)?", entry, re.I)
                for entry in entries
            ):
                return PluginStatus("opencode", "Installed", "local config",
                                    "Plugin registered; runtime loading not checked",
                                    scope="configured")
    return None


def _codex_local_status() -> PluginStatus | None:
    """Verify the official user-scoped registration without starting Codex.

    A marketplace checkout, receipt or orphaned cache alone is not evidence
    of an installed plugin. Unknown layouts fall back to the CLI.
    """
    if tomllib is None:
        return None
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    try:
        with (home / "config.toml").open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, ValueError, UnicodeError):
        return None
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entry = plugins.get("ponytail@ponytail")
    if not isinstance(entry, dict):
        return None
    enabled = entry.get("enabled", True)
    if enabled is False:
        return PluginStatus("codex", "Disabled", "local config",
                            "Disabled in user config", scope="user")
    if enabled is not True:
        return None

    cache = home / "plugins" / "cache" / "ponytail" / "ponytail"
    try:
        for version_dir in cache.iterdir():
            if not version_dir.is_dir():
                continue
            for manifest in ("plugin.json", ".codex-plugin/plugin.json"):
                try:
                    payload = json.loads((version_dir / manifest).read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeError):
                    continue
                if isinstance(payload, dict) and payload.get("name") == "ponytail":
                    return PluginStatus(
                        "codex", "Installed", "local config + cache",
                        "User registration verified; /hooks trust unchecked",
                        scope="user",
                    )
    except OSError:
        pass
    # An enabled registration with no known payload is not a successful
    # verification; let the CLI try other supported layouts.
    return None


def _diagnostic(value: str | None) -> str:
    # Keep the reason short, single-line and safe for terminal rendering.
    line = " ".join(_ANSI.sub("", value or "").split())
    return "".join(c for c in line if c.isprintable())[:160]


def probe_agent_detail(agent: str) -> PluginStatus:
    if agent not in _COMMANDS or not shutil.which(agent):
        return PluginStatus(agent, "Unavailable", "PATH", "CLI not found")
    if agent == "codex":
        local = _codex_local_status()
        if local is not None:
            return local
    command = _COMMANDS[agent]
    reason = ""
    for attempt in range(2):
        try:
            result = subprocess.run(
                command, check=False, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, errors="replace",
                timeout=_TIMEOUT, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            reason = f"Inventory timed out after {_TIMEOUT}s"
            if attempt == 0:
                # Limit Codex discovery to Ponytail on the second attempt.
                # A scoped negative result is not a complete inventory.
                if agent == "codex":
                    command = (*_COMMANDS[agent], "--marketplace", "ponytail")
                continue
            break
        except (OSError, UnicodeError) as exc:
            reason = f"Cannot run inventory ({type(exc).__name__})"
            break
        if result.returncode != 0:
            detail = _diagnostic(getattr(result, "stderr", "") or result.stdout)
            if (agent == "copilot" and result.returncode == 127
                    and "github copilot cli was not found" in detail.lower()):
                return PluginStatus(agent, "Unavailable", "CLI launcher",
                                    "Copilot CLI not installed")
            reason = f"Inventory exit {result.returncode}" + (f": {detail}" if detail else "")
            break
        state = (_from_json(agent, result.stdout) if agent in ("claude", "codex", "copilot")
                 else _from_text(result.stdout, gemini=agent == "gemini"))
        if agent == "codex" and command != _COMMANDS[agent] and state == "Missing":
            reason = "Full inventory timed out; Ponytail marketplace has no match"
            break
        if state != "Unverified":
            reason = {"Installed": "Plugin registered; runtime loading not checked",
                      "Disabled": "Plugin is disabled",
                      "Missing": "Not in recognized plugin inventory"}[state]
            if state == "Installed" and agent == "codex":
                reason = "Registered; review lifecycle hook trust in /hooks"
            return PluginStatus(agent, state, "CLI inventory", reason)
        reason = "Unrecognized or unhealthy plugin inventory"
        break
    if agent == "opencode":
        configured = _opencode_config()
        if configured is not None:
            return configured
    return PluginStatus(agent, "Unverified", "CLI inventory", reason)


def probe_agent(agent: str) -> str:
    """Compatibility wrapper for callers that only need the state."""
    return probe_agent_detail(agent).state


def summary(statuses: dict[str, str]) -> str:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agents", nargs="*", choices=None)
    parser.add_argument("--verify", action="store_true",
                        help="Fail if any requested integration is not registered")
    args = parser.parse_args()
    agents = args.agents or list(AGENTS)
    if any(agent not in AGENTS for agent in agents):
        parser.error("Unsupported agent")
    with ThreadPoolExecutor(max_workers=len(AGENTS)) as pool:
        results = list(pool.map(probe_agent_detail, agents))
    for result in results:
        print(f"Ponytail / {LABELS[result.agent]}: {result.state} "
              f"({result.source}: {result.reason})")
    return int(args.verify and any(result.state != "Installed" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
