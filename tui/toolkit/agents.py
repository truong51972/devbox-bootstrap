"""Independent agent discovery and integration evidence."""
from concurrent.futures import ThreadPoolExecutor
import shutil

from tui.agent_status import AGENTS, LABELS, discover_agents, probe_agent_detail
from tui.rtk_status import inspect_rtk
from .native import native


def agent_list(_value, _cwd):
    return "\n".join(f"{LABELS[a]:<18} {shutil.which(a) or 'Unavailable'}" for a in AGENTS)


def matrix(_value, _cwd):
    availability = discover_agents()
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = pool.submit(inspect_rtk, availability)
        ponytail = dict(zip(AGENTS, pool.map(probe_agent_detail, AGENTS)))
        rtk = pending.result()
    rows = [f"RTK binary: {rtk.binary.state}", f"{'Agent':<18} {'CLI':<13} {'RTK':<16} Ponytail"]
    for a in AGENTS:
        r = rtk.agents.get(a)
        mode = r.state + (" (rules)" if r.source == "instructions" else "") if r else "Unknown"
        rows.append(f"{LABELS[a]:<18} {'Available' if availability[a] != 'Unavailable' else 'Unavailable':<13} {mode:<16} {ponytail[a].state}")
        if r and r.state not in ("Installed", "Unavailable"):
            rows.append(f"  RTK: {r.reason}")
        if ponytail[a].state not in ("Installed", "Unavailable"):
            rows.append(f"  Ponytail: {ponytail[a].reason}")
    return "\n".join(rows) + "\nRegistration evidence only; runtime and hook trust not verified."


def skills(value, cwd):
    if value not in ("", "global", "project"):
        raise ValueError("Scope: global or project.")
    args = ["skills", "list"] + (["-g"] if value != "project" else [])
    return native(args, cwd=cwd, timeout=12)
