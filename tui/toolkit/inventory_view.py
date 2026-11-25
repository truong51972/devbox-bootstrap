"""Structured, responsive inventory tables; no I/O from render functions."""
from __future__ import annotations

from prompt_toolkit.data_structures import Point
from tui.ui import Entry, KeyboardList, focused_status_style, status_style
from .native import safe_text
from .inventory_models import AgentRow, ToolRow, AgentMatrix

SHORT_STATE = {
    "Unavailable": "N/A", "Unverified": "Unverif.",
    "Not checked": "Unchecked", "Available": "Ready",
    "Installed": "Installed", "Disabled": "Disabled",
}


def clip(text, width):
    text = safe_text(str(text)).replace("\n", " ").replace("\t", " ")
    if width <= 0:
        return ""
    return text if len(text) <= width else text[:max(0, width - 1)] + "…"


def cell(state, width, active=False, *, rules=False):
    label = "Rules" if rules and state == "Installed" else SHORT_STATE.get(state, state)
    return (focused_status_style(state, active), clip(label, width).ljust(width))


class InventoryList(KeyboardList):
    def __init__(self, *args, **kwargs):
        self.rows = {}
        self.matrix = None
        super().__init__(*args, **kwargs)

    def set_snapshot(self, snapshot, preserve=False):
        key, query = self.current_value, self.query
        self.matrix = snapshot if isinstance(snapshot, AgentMatrix) else None
        rows = snapshot.agents if self.matrix else snapshot
        self.rows = {row.key: row for row in rows}
        self.entries = [Entry(row.key, row.name,
                              row.category if isinstance(row, ToolRow) else "Agents",
                              row.state if isinstance(row, ToolRow) else row.cli,
                              (row.state + " " + row.path if isinstance(row, ToolRow) else
                               " ".join((row.cli, row.rtk.state, row.ponytail.state))))
                        for row in rows]
        self.query = query if preserve else ""
        self.index = next((i for i, e in enumerate(self.visible) if preserve and e.key == key), 0)
        self.on_change()

    def cursor_position(self):
        if not self.visible:
            return Point(x=0, y=0)
        return Point(x=0, y=1 + min(self.index, len(self.visible) - 1))

    def render(self):
        width = max(1, self.get_columns() - 1)
        if not self.visible:
            return [("class:muted", "  No matching items.")]
        matrix = self.matrix is not None
        # On compact terminals retain all three agent states using abbreviated
        # cells; complete labels and evidence remain in the details screen.
        if matrix:
            cell_width = min(11, max(4, (width - 12) // 3))
            name_width = max(1, width - 2 - 3 * cell_width)
            header = "  " + clip("Agent", name_width).ljust(name_width) + "".join(
                clip(v, cell_width).ljust(cell_width) for v in ("CLI", "RTK", "Ponytail"))
        else:
            cell_width = min(13, max(7, width // 3))
            name_width = max(1, width - 2 - cell_width)
            header = "  " + clip("Tool", name_width).ljust(name_width) + clip("State", cell_width)
        out = [("class:section", header + "\n")]
        for i, entry in enumerate(self.visible):
            row = self.rows[entry.key]
            active = i == self.index
            style = "class:focus" if active else "class:body"
            out.append((style, ("> " if active else "  ") + clip(row.name, name_width).ljust(name_width)))
            if matrix:
                out.append(cell(row.cli, cell_width, active))
                out.append(cell(row.rtk.state, cell_width, active, rules=row.rtk.source == "instructions"))
                out.append(cell(row.ponytail.state, cell_width, active))
            else:
                out.append(cell(row.state, cell_width, active))
            out.append(("", "\n"))
        return out


def field(label, value, style="class:body"):
    return [("class:muted", "  " + label + ": "),
            (style, safe_text(str(value)) + "\n")]


def detail_fragments(row):
    if row is None:
        return [("class:muted", "  Select an item to inspect.")]
    out = [("class:title", "  " + safe_text(row.name) + "\n\n")]
    if isinstance(row, ToolRow):
        out += field("Category", row.category)
        out += field("State", row.state, status_style(row.state))
        if row.path:
            out += field("Executable", row.path)
        if row.dependencies:
            out += field("Requires", ", ".join(row.dependencies))
        out += [("class:section", "\n  INSTALLATION EVIDENCE\n")]
        out += [("class:body", "  " + safe_text(row.evidence) + "\n")]
        out += [("class:muted", "\n  Detection is not a runtime health check.\n")]
    else:
        out += field("CLI", row.cli, status_style(row.cli))
        if row.path:
            out += field("Path / launcher", row.path)
        for label, plugin in (("RTK", row.rtk), ("PONYTAIL", row.ponytail)):
            out += [("class:section", "\n  " + label + "\n")]
            out += field("State", plugin.state, status_style(plugin.state))
            out += field("Source", plugin.source)
            if plugin.version:
                out += field("Version", plugin.version)
            if plugin.scope:
                out += field("Scope", plugin.scope)
            out += [("class:muted", "  " + safe_text(plugin.reason) + "\n")]
        out += [("class:muted", "\n  Registration only; runtime / hook trust not verified.\n")]
    return out
