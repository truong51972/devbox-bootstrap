"""Independent agent discovery and integration evidence."""
from concurrent.futures import ThreadPoolExecutor
import shutil

from tui.agent_status import AGENTS, LABELS, PluginStatus, discover_agents, probe_agent_detail
from .inventory_models import AgentRow, AgentMatrix
from tui.rtk_status import inspect_rtk
from .native import native


def agent_list(_value, _cwd):
    return "\n".join(f"{LABELS[a]:<18} {shutil.which(a) or 'Unavailable'}" for a in AGENTS)


def agent_matrix():
    availability = discover_agents()
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = pool.submit(inspect_rtk, availability)
        ponytail = dict(zip(AGENTS, pool.map(probe_agent_detail, AGENTS)))
        rtk = pending.result()
    rows = []
    for key in AGENTS:
        cli = "Available" if availability[key] != "Unavailable" else "Unavailable"
        plugin = ponytail[key]
        integration = rtk.agents.get(key) or PluginStatus(key, "Unverified", "inventory", "No integration evidence")
        # A launcher on PATH can exist even when its underlying CLI is missing.
        if plugin.state == "Unavailable" and plugin.source == "CLI launcher":
            cli = "Unavailable"
            integration = PluginStatus(key, "Unavailable", plugin.source, plugin.reason)
        rows.append(AgentRow(key, LABELS[key], cli, shutil.which(key) or "", integration, plugin))
    return AgentMatrix(rtk.binary, tuple(rows))


def matrix(_value, _cwd):
    snapshot = agent_matrix()
    rows = [f"RTK binary: {snapshot.binary.state}", f"{'Agent':<18} {'CLI':<13} {'RTK':<16} Ponytail"]
    for row in snapshot.agents:
        mode = row.rtk.state + (" (rules)" if row.rtk.source == "instructions" else "")
        rows.append(f"{row.name:<18} {row.cli:<13} {mode:<16} {row.ponytail.state}")
        for label, plugin in (("RTK", row.rtk), ("Ponytail", row.ponytail)):
            if plugin.state not in ("Installed", "Unavailable"):
                rows.append(f"  {label}: {plugin.reason}")
    return "\n".join(rows) + "\nRegistration evidence only; runtime and hook trust not verified."


def skills(value, cwd):
    if value not in ("", "global", "project"):
        raise ValueError("Scope: global or project.")
    args = ["skills", "list"] + (["-g"] if value != "project" else [])
    return native(args, cwd=cwd, timeout=12)


def version(value, _cwd):
    if value not in AGENTS:
        raise ValueError("Choose one of: " + ", ".join(AGENTS))
    return native([value, "--version"])


def skill_updates(_value, cwd):
    return native(["skills", "check"], cwd=cwd, timeout=20)
