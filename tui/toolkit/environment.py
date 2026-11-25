"""Environment inventory and desired-state profile inspection."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from tui.catalog import COMPONENTS, GROUPS, inventory, with_dependencies, DEPENDENCIES
from tui.inventory_detail import inspect_component_details
from .inventory_models import ToolRow
from tui.agent_status import AGENTS
from .settings import read_json


def tool_rows():
    states = inventory(quick=True)
    metadata = inspect_component_details()
    categories = {key: group for group, keys in GROUPS for key in keys}
    return tuple(
        ToolRow(code, name, categories.get(code, "OTHER"),
                "Not checked" if states[code] == "Checking" else states[code],
                *metadata.get(code, ("", "Ownership/version not verified")),
                DEPENDENCIES.get(code, ()))
        for code, name in COMPONENTS
    )


def tools(_value, _cwd):
    return "\n".join(f"{row.name:<25} {row.state}\n  " +
                     (row.path + "\n  " if row.path else "") + row.evidence
                     for row in tool_rows()) + "\nUse Install/Upgrade for managed operations."


def profile_plan(value, cwd):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    profile = read_json(path)
    if not isinstance(profile, dict) or set(profile) - {"name", "tools", "integrations"}:
        raise ValueError("Profile must contain name, tools and/or integrations.")
    requested = profile.get("tools", [])
    targets = profile.get("integrations", {})
    known = {code for code, _ in COMPONENTS}
    if not isinstance(requested, list) or any(not isinstance(v, str) or v not in known for v in requested):
        raise ValueError("Unknown profile component.")
    if not isinstance(targets, dict) or set(targets) - {"rtk", "ponytail"}:
        raise ValueError("Unsupported profile integration.")
    for extension, agents in targets.items():
        if not isinstance(agents, list) or any(not isinstance(a, str) or a not in AGENTS for a in agents):
            raise ValueError("Unknown profile agent.")
    if "ponytail" in requested and not targets.get("ponytail"):
        raise ValueError("Ponytail requires explicit integration targets.")
    states = inventory(quick=True)
    wanted = [v for v in requested if v != "ponytail" and states[v] != "Installed"]
    selected, dependencies = with_dependencies(wanted, states)
    rows = ["Desired state (preview only):", "Install/inspect: " + (", ".join(selected) or "None"),
            "Dependencies: " + (", ".join(dependencies) or "None")]
    for extension, agents in targets.items():
        rows.append(f"{extension}: " + (", ".join(agents) or "No targets"))
        for agent in agents:
            if not shutil.which(agent):
                rows.append(f"  {agent}: CLI unavailable")
    rows.append("No configuration is changed. Review each action separately.")
    return "\n".join(rows)
