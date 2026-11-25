"""Responsive shared presentation; controller owns state and actions."""
from __future__ import annotations

from prompt_toolkit.filters import Condition
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.layout import HSplit, VSplit, DynamicContainer, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

WIDE_LAYOUT_MIN = 94
SPLIT_SPACING = 3  # One divider column and two VSplit padding columns.


def detail_panel_width(columns: int) -> int:
    """Reserve half of the available split width, rounded toward details."""
    return max(1, (columns - SPLIT_SPACING + 1) // 2)


def fit_shortcuts(hints: str, width: int) -> str:
    """Keep complete key/label pairs; prioritize primary action, Back and Help."""
    if width <= 0:
        return ""
    tokens = [part.strip() for part in hints.split("  ") if part.strip()]
    if get_cwidth("  ".join(tokens)) <= width:
        return "  ".join(tokens)
    essential = [part for part in tokens if part.startswith(("Enter ", "Esc", "? ", "F1 "))]
    result = []
    for part in essential + [part for part in tokens if part not in essential]:
        if get_cwidth("  ".join(result + [part])) <= width:
            result.append(part)
    return "  ".join(result) or (tokens[0][:width] if tokens else "")


class DevboxViews:
    def _text(self, render, *, height=None, width=None):
        return Window(
            content=FormattedTextControl(render, focusable=False, show_cursor=False),
            height=height, width=width, wrap_lines=True, style="class:body",
        )

    def _divider(self):
        return Window(height=1, char="─", style="class:divider")

    @staticmethod
    def _truncate(message: str, width: int) -> str:
        """Prevent one-line header/footer/notice text from being clipped mid-key."""
        if width <= 0:
            return ""
        return message if len(message) <= width else (
            message[:max(0, width - 1)] + "…"
        )

    def _page(self, title, body, shortcut):
        def header_text():
            width = max(0, self.columns() - 2)
            name = title() if callable(title) else title
            value = self._truncate(
                f"  DEVBOX / {name.upper()}", width
            )
            return [("class:header", value)]

        def notice_text():
            return [(self.message_style, self._truncate(
                "  " + self.message, max(0, self.columns() - 1)
            ))]

        def footer_text():
            width = max(0, self.columns() - 2)
            name = title() if callable(title) else title
            hints = shortcut() if callable(shortcut) else shortcut
            value = self._confirm_shortcuts() if name == "Confirm" else hints
            if "? Help" not in value and "F1 Help" not in value and name not in ("Keyboard help", "Execution"):
                value += "  ? Help"
            return [("class:footer", "  " + fit_shortcuts(value, max(0, width - 2)))]

        return HSplit([
            self._text(header_text, height=1),
            self._divider(),
            body,
            self._text(notice_text, height=1),
            self._text(footer_text, height=1),
        ])

    def _build_views(self) -> None:
        self.views["home"] = self._page(
            "Overview",
            DynamicContainer(self._home_layout),
            lambda: self.menu.shortcut_hints(**{"r": "Check source", "u": "Review source" if self.menu.current_value == "devbox_info" else ""}) + "  Ctrl+K Search",
        )
        self.views["devbox_info"] = self._page(
            "Info", HSplit([self.devbox_info_view, self._divider(), self.devbox_info_actions.window]),
            "↑↓ Choose  Enter Open  R Check update  U Review update  Tab Scroll  Esc Back",
        )
        self.devbox_info_actions.window.height = Dimension(min=3, preferred=4, max=5)
        self.views["update_prompt"] = self._page(
            "Update available", HSplit([
                self._text(self._update_details, height=Dimension(min=5, preferred=9)),
                self._divider(), self.update_choices.window,
            ]), "↑↓ Choose   Enter Confirm   y Yes   n No   Esc No",
        )
        self.views["select"] = self._page(
            "Components",
            HSplit([
                DynamicContainer(self._selection_layout),
                DynamicContainer(lambda: self._filter_layout()),
            ]),
            lambda: self.selector.shortcut_hints(Enter="Review", a="All filtered"),
        )
        self.views["cleaner"] = self._page(
            "Cleaner", HSplit([DynamicContainer(self._cleaner_layout),
                               DynamicContainer(self._filter_layout)]),
            lambda: self.cleaner_list.shortcut_hints(Enter="Review", a="Safe preset", r="Scan"),
        )
        self.views["cleaner_info"] = self._page("Cleaner details", self.info_view, "Esc Back to Cleaner")
        self.views["confirm"] = self._page(
            "Confirm", DynamicContainer(self._confirm_layout),
            "Space Toggle options   d Dry-run   Enter Execute   Esc Back",
        )
        self.views["run"] = self._page(
            "Execution", DynamicContainer(self._run_layout),
            "l Expand/collapse output   Task active · exit locked",
        )
        self.views["result"] = self._page(
            "Result", self.results_view,
            "l View log   Enter Back   Esc Back   ? Help",
        )
        self.views["logs"] = self._page(
            "History", HSplit([
                DynamicContainer(self._logs_layout),
                DynamicContainer(lambda: self._filter_layout()),
            ]),
            lambda: self.log_files.shortcut_hints(Enter="View log"),
        )
        self.views["view_log"] = self._page(
            "Log viewer", self.history_view,
            "↑↓/PgUp/PgDn Scroll   o External pager   Esc Back",
        )
        self.views["help"] = self._page(
            "Keyboard help", self.help_view, "Esc Back",
        )
        self.views["preview_detail"] = self._page("Details", self.info_view, "↑↓ Scroll  Esc Back")
        self.views["info"] = self._page(
            "Component details", self.info_view,
            "Esc Back to components",
        )

    def _layout(self, key: str, build):
        """Keep Window/HSplit instances stable across prompt_toolkit redraws."""
        if key not in self._layout_cache:
            self._layout_cache[key] = build()
        return self._layout_cache[key]

    def _divider_v(self):
        return Window(char="│", width=1, style="class:divider")

    def _master_detail(self, key, widget, render, *, medium_height=0, min_columns=64):
        """One responsive split policy, stable cached Windows and compact fallback."""
        if self.columns() >= WIDE_LAYOUT_MIN:
            return self._layout(key + "-wide", lambda: VSplit([
                widget.window, self._divider_v(),
                self._text(render, width=lambda: Dimension.exact(detail_panel_width(self.columns()))),
            ], padding=1))
        if medium_height and self.rows() >= 25 and self.columns() >= min_columns:
            return self._layout(key + "-medium", lambda: HSplit([
                widget.window, self._divider(), self._text(render, height=medium_height),
            ]))
        return widget.window

    def _home_layout(self):
        if self.columns() >= WIDE_LAYOUT_MIN:
            return self._layout("home-wide", lambda: VSplit([
                self.menu.window, self._divider_v(),
                self._text(self._home_details, width=lambda: Dimension.exact(detail_panel_width(self.columns()))),
            ], padding=1))
        if self.rows() >= 26:
            return self._layout("home-medium", lambda: HSplit([
                self.menu.window, self._divider(),
                self._text(self._home_details, height=lambda: Dimension.exact(10 if self.menu.current_value == "devbox_info" else 5)),
            ]))
        return self.menu.window

    def _selection_layout(self):
        return self._master_detail("select", self.selector, self._component_details, medium_height=6)

    def _filter_layout(self):
        from prompt_toolkit.layout import ConditionalContainer
        return self._layout("filter", lambda: ConditionalContainer(
            content=self.filter_input,
            filter=Condition(lambda: self.filter_active),
        ))

    def _confirm_shortcuts(self):
        primary = "Enter Preview" if self.dry_run and self.action != "update" else {
            "install": "Enter Install", "upgrade": "Enter Upgrade",
            "clean": "Enter Clean", "update": "Enter Update",
        }.get(self.action, "Enter Run")
        keys = [primary, "Esc Back"]
        if self.action != "update":
            keys.insert(1, "d Dry-run")
        if self.options.entries:
            keys.extend(["Space Options", "Tab Focus"])
        return "  ".join(keys)

    def _confirm_mode(self):
        preview = self.dry_run and self.action != "update"
        requires_consent = (self.action == "clean" and bool(self.options.entries)
                            and "risk" not in self.options.current_values and not preview)
        return [
            ("class:warning" if preview or requires_consent else "class:running",
             "  DRY RUN — no changes\n" if preview else
             "  MANUAL CLEANUP — consent required\n" if requires_consent else
             "  APPLY CHANGES — Enter to confirm\n"),
        ]

    def _refresh_confirm_plan(self):
        if hasattr(self, "confirm_plan"):
            value = self._selection_summary()
            if self.confirm_plan.text != value:
                self.confirm_plan.text = value
        self._invalidate()

    def _confirm_layout(self):
        def build():
            # The plan is focusable/scrollable even when there are no options.
            children = [self._text(self._confirm_mode, height=1), self._divider(),
                        self.confirm_plan]
            if self.options.entries:
                children += [
                    self._divider(),
                    self._text(lambda: [("class:section",
                        "  REQUIRED CONSENT" if self.action == "clean" else
                        "  OPTIONS (OFF BY DEFAULT)")], height=1),
                    self.options.window,
                ]
                # Allocate only as much space as the actual choices need.
                self.options.window.height = Dimension(
                    min=1, preferred=min(8, len(self.options.entries) + 2), max=12)
            return HSplit(children)
        return self._layout("confirm", build)

    def _confirm_focus(self):
        return self.options.window if self.options.entries else self.confirm_plan

    def _run_layout(self):
        return self._layout("run", lambda: HSplit([
            self._text(self._progress_tokens, height=2),
            self.status_view,
            self._divider(),
            self._text(lambda: [
                ("class:section", "  EXPANDED OUTPUT" if self.expanded_log
                 else "  RECENT OUTPUT"),
            ], height=1),
            self.log_view,
        ]))

    def _logs_layout(self):
        return self._master_detail("logs", self.log_files, self._history_details)

    def _cleaner_layout(self):
        summary = lambda: self._text(self._cleaner_summary, height=2)
        if self.columns() >= WIDE_LAYOUT_MIN:
            return self._layout("cleaner-wide", lambda: HSplit([
                summary(), self._divider(), VSplit([
                    self.cleaner_list.window, self._divider_v(),
                    self._text(self._cleaner_details, width=lambda: Dimension.exact(detail_panel_width(self.columns()))),
                ], padding=1),
            ]))
        if self.rows() >= 25 and self.columns() >= 64:
            return self._layout("cleaner-medium", lambda: HSplit([
                summary(), self._divider(), self.cleaner_list.window, self._divider(),
                self._text(self._cleaner_details, height=6),
            ]))
        return self._layout("cleaner-narrow", lambda: HSplit([
            summary(), self._divider(), self.cleaner_list.window,
        ]))
