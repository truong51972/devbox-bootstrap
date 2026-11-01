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


STYLE = {
    "header": "bg:default fg:ansicyan bold",
    "title": "fg:ansiwhite bold",
    "section": "fg:ansibrightblack bold",
    "muted": "fg:ansibrightblack",
    "divider": "fg:ansibrightblack",
    "focus": "bg:ansiblue fg:ansiwhite bold",
    "checked": "fg:ansigreen bold",
    "installed": "fg:ansigreen",
    "missing": "fg:ansibrightblack",
    "warning": "fg:ansiyellow",
    "error": "fg:ansired",
    "running": "fg:ansicyan bold",
    "footer": "fg:ansiwhite",
    "statusbar": "fg:ansibrightblack",
    "body": "fg:ansiwhite",
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
    "missing": "",
    "warning": "bold",
    "error": "reverse bold",
    "running": "bold",
    "footer": "bold",
    "statusbar": "",
    "body": "",
}
THEMES = {"minimal": STYLE, "mono": MONO_STYLE}

STATUS_STYLES = {
    "Installed": "class:installed",
    "Missing": "class:missing",
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
}


@dataclass(frozen=True)
class Entry:
    key: str
    label: str
    group: str = ""
    status: str = ""
    description: str = ""


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
        get_columns: Callable[[], int] = lambda: 100,
        on_filter: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_dry: Callable[[], None] | None = None,
        on_details: Callable[[], None] | None = None,
        on_theme: Callable[[], None] | None = None,
    ) -> None:
        self.entries = list(entries)
        self.multiple = multiple
        self.selected: set[str] = set()
        self.index = 0
        self.query = ""
        self.get_columns = get_columns
        self.on_change = on_change

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

        if multiple:
            @kb.add("a")
            def _all(_event) -> None:
                self.selected = {item.key for item in self.visible}
                self.on_change()

            @kb.add("n")
            def _none(_event) -> None:
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

    @property
    def visible(self) -> list[Entry]:
        term = self.query.casefold().strip()
        if not term:
            return self.entries
        return [
            entry for entry in self.entries
            if term in (entry.label + " " + entry.group + " "
                        + entry.description + " " + entry.key).casefold()
        ]

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
        return [entry.key for entry in self.entries if entry.key in self.selected]

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
        if current is not None:
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
            return [("class:muted", "  No matching components. Clear the filter with Esc.")]
        last_group = None
        wide = self.get_columns() >= 105
        for i, entry in enumerate(values):
            if entry.group and entry.group != last_group:
                if fragments:
                    fragments.append(("", "\n"))
                fragments.append(("class:section", f"  {entry.group}\n"))
                last_group = entry.group
            active = i == self.index
            prefix = "[x]" if entry.key in self.selected and self.multiple else (
                "[ ]" if self.multiple else "   "
            )
            marker = ">" if active else " "
            text = f" {marker} {prefix} {entry.label}"
            if wide and entry.status:
                text = f"{text:<34} {entry.status}"
            fragments.append(("class:focus" if active else
                              "class:checked" if entry.key in self.selected else
                              "class:body", text + "\n"))
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
