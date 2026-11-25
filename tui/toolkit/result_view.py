"""Reusable result table and semantic report rendering."""
from prompt_toolkit.data_structures import Point
from tui.ui import Entry, KeyboardList
from .inventory_view import clip
from .native import safe_text
from .results import TableData, ReportData, ResourceData, TextData

class ResultTable(KeyboardList):
    def __init__(self, *args, **kwargs):
        self.data = TableData((), ())
        self.sort_column = -1
        self.descending = False
        super().__init__(*args, **kwargs)

    def set_data(self, data, preserve=False):
        key, query = self.current_value, self.query
        self.data = data
        self.entries = [Entry(str(i), " ".join(c.value for c in row)) for i, row in enumerate(data.rows)]
        self.query = query if preserve else ""
        self.index = next((i for i, e in enumerate(self.visible) if preserve and e.key == key), 0)
        self.sort_column = -1
        self.on_change()

    @property
    def row(self):
        return self.data.rows[int(self.current_value)] if self.current_value is not None else None

    def sort_next(self):
        if not self.data.columns:
            return
        self.sort_column = (self.sort_column + 1) % len(self.data.columns)
        def key(entry):
            row = self.data.rows[int(entry.key)]
            return row[self.sort_column].value.casefold() if self.sort_column < len(row) else ""
        self.entries.sort(key=key)
        self.index = 0
        self.on_change()

    def cursor_position(self):
        return Point(x=0, y=self.index + 1 if self.visible else 0)

    def render(self):
        if not self.visible:
            return [("class:muted", "  No matching rows. Refresh or change the filter.")]
        width = max(1, self.get_columns() - 2)
        n = len(self.data.columns)
        if not n:
            return []
        # Hide trailing columns only on very narrow panes; details expose all fields.
        count = min(n, max(1, width // 9))
        available = max(count, width - 2 - (count - 1))
        weights = [max(7, min(22, len(c) + 3)) for c in self.data.columns[:count]]
        widths = [max(1, available * w // sum(weights)) for w in weights]
        widths[-1] += available - sum(widths)
        out = [("class:section", "  " + " ".join(clip(c, w).ljust(w) for c, w in zip(self.data.columns, widths)) + "\n")]
        for i, e in enumerate(self.visible):
            active = i == self.index
            out.append(("class:focus" if active else "class:body", "> " if active else "  "))
            row = self.data.rows[int(e.key)]
            for c, w in zip(row, widths):
                style = "class:" + c.tone
                if active:
                    style = "class:focus" if c.tone in ("body", "muted") else "class:focus " + style
                out.append((style, clip(c.value, w).ljust(w) + " "))
            out.append(("", "\n"))
        return out

    def detail(self):
        return [fragment for label, cell in zip(self.data.columns, self.row or ())
                for fragment in (("class:section", "  " + label + "\n"), ("class:" + cell.tone, "  " + safe_text(cell.value) + "\n\n"))]

def fragments(result, width=80):
    out = [("class:" + result.tone, "  " + safe_text(result.summary) + "\n\n")]
    if isinstance(result.data, ReportData):
        for name, c in result.data.fields:
            out.extend((("class:section", "  " + name + "\n"), ("class:" + c.tone, "  " + safe_text(c.value) + "\n\n")))
    elif isinstance(result.data, ResourceData):
        for metric in result.data.metrics:
            out.extend((("class:section", "  " + metric.name + "\n"), ("class:body", "  " + metric.value + "\n")))
            if metric.ratio is not None:
                ratio = min(1., max(0., metric.ratio))
                count = min(30, max(5, width - 12))
                filled = round(count * ratio)
                out.append(("class:warning" if ratio >= .85 else "class:installed", "  " + "█" * filled + "░" * (count-filled) + f" {ratio:.0%}\n"))
            out.append(("", "\n"))
    elif isinstance(result.data, TextData):
        out.append(("class:body", safe_text(result.data.text) + "\n"))
    for note in result.notes:
        out.append(("class:muted", "\n  " + safe_text(note)))
    if result.partial:
        out.append(("class:warning", "\n  Partial results — scan/output limit reached."))
    return out
