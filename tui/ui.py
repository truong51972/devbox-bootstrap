"""Reusable keyboard-driven terminal widgets and the Devbox visual system.

No extra runtime dependency: these are prompt_toolkit primitives. Selection,
focus, and read-only status deliberately have different visual treatments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.utils import get_cwidth


STYLE = {
    "header": "bg:default fg:ansicyan bold",
    "title": "fg:default bold",
    "section": "fg:ansicyan bold",
    "muted": "fg:ansibrightblack",
    "divider": "fg:ansibrightblack",
    "focus": "bg:ansiblue fg:ansiwhite bold",
    "checked": "fg:ansigreen bold",
    "installed": "fg:ansibrightgreen",
    "missing": "fg:ansibrightred bold",
    "warning": "fg:ansibrightyellow",
    "error": "fg:ansibrightred bold",
    "running": "fg:ansicyan bold",
    "footer": "fg:default",
    "key": "fg:ansicyan bold",
    "breadcrumb": "fg:default",
    "statusbar": "fg:ansibrightblack",
    "body": "fg:default",
}
MONO_STYLE = {
    # Works on monochrome terminals and themes without ANSI palette support.
    "header": "bold",
    "title": "bold",
    "section": "bold",
    "muted": "",
    "divider": "",
    "focus": "reverse bold",
    "checked": "bold",
    "installed": "bold",
    "missing": "underline bold",
    "warning": "bold",
    "error": "reverse bold",
    "running": "bold",
    "footer": "",
    "key": "bold",
    "breadcrumb": "",
    "statusbar": "",
    "body": "",
}
THEMES = {"minimal": STYLE, "mono": MONO_STYLE}

STATUS_STYLES = {
    "Installed": "class:installed",
    "Up to date": "class:installed",
    "Update available": "class:warning",
    "Update unknown": "class:warning",
    "Update blocked": "class:warning",
    "Manual update": "class:warning",
    "Not applicable": "class:muted",
    "Check failed": "class:error",
    "Unknown": "class:muted",
    "Available": "class:installed",
    "Not checked": "class:warning",
    "Missing": "class:missing",
    "Unverified": "class:warning",
    "Partial": "class:warning",
    "PARTIAL": "class:warning",
    "SUCCESS": "class:installed",
    "PREVIEW": "class:warning",
    "Checking": "class:running",
    "Unavailable": "class:muted",
    "Disabled": "class:warning",
    "RUNNING": "class:running",
    "QUEUED": "class:muted",
    "PENDING": "class:muted",
    "FAILED": "class:error",
    "NOT_RUN": "class:muted",
    "INSTALLED": "class:installed",
    "CONFIGURED": "class:installed",
    "UPDATED": "class:installed",
    "UP_TO_DATE": "class:installed",
    "SKIPPED": "class:warning",
    "PLANNED": "class:warning",
    "NO_RECLAIM": "class:muted",
    "NOTHING_TO_CLEAN": "class:muted",
    "COMPLETED": "class:installed",
    "CLEANED": "class:installed",
}

def cell_truncate(text: str, width: int) -> str:
    """Fit terminal display cells (not Python character count)."""
    if width <= 0:
        return ""
    if get_cwidth(text) <= width:
        return text
    out = []
    used = 0
    for char in text:
        size = get_cwidth(char)
        if used + size > width - 1:
            break
        out.append(char)
        used += size
    return "".join(out) + "…"


def status_style(status: str) -> str:
    """Use the same semantic palette for component, run and cleaner rows."""
    if status.endswith(" updates"):
        return "class:warning"
    if status in STATUS_STYLES:
        return STATUS_STYLES[status]
    if status.startswith(("SAFE | ", "MANUAL | ")):
        risk, _, state = status.partition(" | ")
        if state == "Checking...":
            return "class:running"
        if state == "Unavailable":
            return "class:muted"
        return "class:installed" if risk == "SAFE" else "class:warning"
    return "class:muted"


def focused_status_style(status: str, active: bool) -> str:
    style = status_style(status)
    if not active:
        return style
    # Muted text would be difficult to read on a blue focus background.
    return "class:focus" if style == "class:muted" else "class:focus " + style


@dataclass(frozen=True)
class Entry:
    key: str
    label: str
    group: str = ""
    status: str = ""
    description: str = ""
    selectable: bool = True
    status_parts: tuple[tuple[str, str], ...] = ()  # label, semantic state


class KeyboardList:
    """Navigable filtered list, optional multi-selection, no radio glyphs.

    All shortcuts are installed on the focused control because builtin
    controls swallow global Enter/Space keybindings.
    """

    def __init__(
        self,
        entries: Sequence[Entry],
        *,
        on_enter: Callable[[], None],
        on_back: Callable[[], None],
        on_help: Callable[[], None],
        on_change: Callable[[], None],
        multiple: bool = False,
        bulk_select: bool = True,
        bulk_allowed: Callable[[Entry], bool] | None = None,
        on_all: Callable[[], None] | None = None,
        on_manual_selection: Callable[[], None] | None = None,
        empty_text: str = "No matching entries. Press / to edit the filter.",
        get_columns: Callable[[], int] = lambda: 100,
        on_filter: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_dry: Callable[[], None] | None = None,
        on_details: Callable[[], None] | None = None,
        on_theme: Callable[[], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
        on_favorite: Callable[[], None] | None = None,
        on_sort: Callable[[], None] | None = None,
        on_raw: Callable[[], None] | None = None,
        on_related: Callable[[], None] | None = None,
        on_edit: Callable[[], None] | None = None,
        on_update: Callable[[], None] | None = None,
        on_adopt: Callable[[], None] | None = None,
        on_cycle: Callable[[], None] | None = None,
        on_retry: Callable[[], None] | None = None,
    ) -> None:
        self.entries = list(entries)
        self.multiple = multiple
        self.empty_text = empty_text
        self.selected: set[str] = set()
        self.index = 0
        self.query = ""
        self.get_columns = get_columns
        self.on_change = on_change
        self.on_manual_selection = on_manual_selection
        self.entry_filter: Callable[[Entry], bool] | None = None
        self._shortcuts = [("Enter", "Open"), ("↑↓", "Move")]
        if multiple:
            self._shortcuts.append(("Space", "Select"))
        if multiple and bulk_select:
            self._shortcuts.extend((("a", "All filtered" if on_all is None and bulk_allowed is None else "Preset"), ("n", "Clear")))
        for key, label, callback in (
            ("u", "Updates", on_update), ("c", "Retry checks", on_retry),
            ("g", "Status filter", on_cycle), ("r", "Refresh", on_refresh),
            ("/", "Filter", on_filter), ("i", "Details", on_details),
            ("x", "Actions", on_related), ("s", "Sort", on_sort),
            ("f", "Favorite", on_favorite), ("e", "Edit", on_edit),
            ("v", "Raw", on_raw), ("m", "Adopt", on_adopt),
            ("t", "Theme", on_theme), ("d", "Dry-run", on_dry),
            ("q", "Quit", on_quit),
        ):
            if callback:
                self._shortcuts.append((key, label))
        self._shortcuts.extend((("Esc", "Back"), ("?", "Help")))

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(_event) -> None:
            self.move(-1)

        @kb.add("down")
        @kb.add("j")
        def _down(_event) -> None:
            self.move(1)

        @kb.add("home")
        def _home(_event) -> None:
            self.index = 0
            self.on_change()

        @kb.add("end")
        def _end(_event) -> None:
            self.index = max(0, len(self.visible) - 1)
            self.on_change()

        @kb.add(" ")
        def _space(_event) -> None:
            if self.multiple:
                self.toggle()

        @kb.add("enter")
        def _enter(_event) -> None:
            on_enter()

        @kb.add("escape")
        def _back(_event) -> None:
            on_back()

        @kb.add("?")
        def _help(_event) -> None:
            on_help()

        @kb.add("c-q")
        def _quit(_event) -> None:
            if on_quit:
                on_quit()

        if on_filter:
            @kb.add("/")
            def _filter(_event) -> None:
                on_filter()

        if on_details:
            @kb.add("i")
            def _details(_event) -> None:
                on_details()

        if on_favorite:
            @kb.add("f")
            def _favorite(_event) -> None:
                on_favorite()

        if on_sort:
            @kb.add("s")
            def _sort(_event):
                on_sort()
        if on_raw:
            @kb.add("v")
            def _raw(_event):
                on_raw()
        if on_related:
            @kb.add("x")
            @kb.add("X")
            def _related_shortcut(_event):
                on_related()
            @kb.add("a")
            def _related(_event):
                on_related()
        if on_edit:
            @kb.add("e")
            def _edit(_event):
                on_edit()

        if on_adopt:
            @kb.add("m")
            @kb.add("M")
            def _adopt(_event):
                on_adopt()

        if on_update:
            @kb.add("u")
            @kb.add("U")
            def _update(_event):
                on_update()

        if on_refresh:
            @kb.add("r")
            @kb.add("R")
            def _refresh(_event) -> None:
                on_refresh()

        if on_cycle:
            @kb.add("g")
            @kb.add("G")
            def _cycle(_event):
                on_cycle()

        if on_retry:
            @kb.add("c")
            @kb.add("C")
            def _retry(_event):
                on_retry()

        if multiple and bulk_select:
            @kb.add("a")
            @kb.add("A")
            def _all(_event) -> None:
                if on_all is not None:
                    on_all()
                    return
                # Preserve selected items hidden by an active filter.
                if bulk_allowed is None:
                    self.selected.update(item.key for item in self.visible if item.selectable)
                else:
                    # A safe preset replaces prior manual selections, even if hidden.
                    self.selected = {item.key for item in self.visible if item.selectable and bulk_allowed(item)}
                self.on_change()

            @kb.add("n")
            @kb.add("N")
            def _none(_event) -> None:
                if self.on_manual_selection is not None:
                    self.on_manual_selection()
                self.selected.clear()
                self.on_change()

        if on_quit:
            @kb.add("q")
            def _quit_shortcut(_event) -> None:
                on_quit()

        if on_theme:
            @kb.add("t")
            def _theme(_event) -> None:
                on_theme()

        if on_dry:
            @kb.add("d")
            def _dry(_event) -> None:
                on_dry()

        control = FormattedTextControl(
            self.render, focusable=True, key_bindings=kb,
            show_cursor=False, get_cursor_position=self.cursor_position,
        )
        self.window = Window(
            content=control, wrap_lines=False, always_hide_cursor=True,
            allow_scroll_beyond_bottom=False, style="class:body",
        )

    def shortcut_hints(self, **labels) -> str:
        """Render hints from registered callbacks, with context-specific labels."""
        return "  ".join(f"{key} {labels.get(key, label)}" for key, label in self._shortcuts
                         if labels.get(key, label))

    @property
    def visible(self) -> list[Entry]:
        entries = self.entries if self.entry_filter is None else [e for e in self.entries if self.entry_filter(e)]
        terms = self.query.casefold().split()
        if not terms:
            return entries
        return [entry for entry in entries if all(term in (
            entry.label + " " + entry.group + " " + entry.description + " " + entry.key
        ).casefold() for term in terms)]

    @property
    def current(self) -> Entry | None:
        values = self.visible
        return values[min(self.index, len(values) - 1)] if values else None

    @property
    def current_value(self) -> str | None:
        entry = self.current
        return entry.key if entry is not None else None

    @property
    def current_values(self) -> list[str]:
        return [entry.key for entry in self.entries if entry.selectable and entry.key in self.selected]

    @current_values.setter
    def current_values(self, values: Sequence[str]) -> None:
        self.selected = set(values)
        self.on_change()

    @property
    def values(self) -> list[tuple[str, str]]:
        return [(entry.key, entry.label) for entry in self.entries]

    def set_query(self, query: str) -> None:
        self.query = query
        self.index = 0
        self.on_change()

    def move(self, delta: int) -> None:
        self.index = max(0, min(self.index + delta, len(self.visible) - 1))
        self.on_change()

    def toggle(self) -> None:
        current = self.current
        if current is not None and current.selectable:
            if self.on_manual_selection is not None:
                self.on_manual_selection()
            if current.key in self.selected:
                self.selected.remove(current.key)
            else:
                self.selected.add(current.key)
        self.on_change()

    def cursor_position(self) -> Point:
        values = self.visible
        row = 0
        previous_group = None
        for i, entry in enumerate(values):
            if entry.group and entry.group != previous_group:
                row += 2 if row else 1  # heading plus preceding blank
                previous_group = entry.group
            if i == self.index:
                return Point(x=0, y=row)
            row += 1
        return Point(x=0, y=0)

    def render(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        values = self.visible
        if not values:
            return [("class:muted", "  " + self.empty_text)]

        last_group = None
        width = max(1, self.get_columns())
        content_width = max(1, width - 2)  # leave a small right gutter
        for i, entry in enumerate(values):
            if entry.group and entry.group != last_group:
                if fragments:
                    fragments.append(("", "\n"))
                fragments.append(("class:section", f"  {entry.group}\n"))
                last_group = entry.group

            active = i == self.index
            prefix = ("[-]" if not entry.selectable else "[x]" if entry.key in self.selected else "[ ]") if self.multiple else "   "
            marker = ">" if active else " "
            start = f" {marker} {prefix} "
            # Never let the status column crowd out the label on narrow panes.
            parts = entry.status_parts or ((entry.status, entry.status),)
            status_text = " · ".join(label for label, _ in parts)
            show_status = bool(status_text and width >= 43)
            # Keep enough room to recognize the resource even with two statuses.
            show_status = show_status and get_cwidth(status_text) + 2 + get_cwidth(start) + 8 <= content_width
            reserved = get_cwidth(status_text) + 2 if show_status else 0
            label_width = max(0, content_width - get_cwidth(start) - reserved)
            label = cell_truncate(entry.label, label_width)

            row_style = ("class:focus" if active else
                         "class:muted" if not entry.selectable else
                         "class:checked" if entry.key in self.selected else
                         "class:body")
            text = start + label
            if show_status:
                gap = max(2, content_width - get_cwidth(text) - get_cwidth(status_text))
                fragments.append((row_style, text + " " * gap))
                for pos, (label, state) in enumerate(parts):
                    if pos:
                        fragments.append((row_style, " · "))
                    fragments.append((focused_status_style(state, active), label + ("\n" if pos == len(parts) - 1 else "")))
            else:
                fragments.append((row_style, text + "\n"))
        return fragments


def read_only_window(render: Callable[[], list[tuple[str, str]]],
                     *, focusable: bool = False, bindings=None) -> Window:
    return Window(
        content=FormattedTextControl(
            render, focusable=focusable, key_bindings=bindings,
            show_cursor=False
        ),
        wrap_lines=True,
        always_hide_cursor=True,
        style="class:body",
    )


def lines(*entries: tuple[str, str]) -> list[tuple[str, str]]:
    return [(f"class:{style}", content + "\n") for style, content in entries]
