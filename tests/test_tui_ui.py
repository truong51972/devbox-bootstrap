"""Visual/layout and keyboard interaction regressions for the minimal TUI."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prompt_toolkit.application.current import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout import HSplit, VSplit, Window
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput

from tui.app import DevboxTUI
from tui.views import detail_panel_width, SPLIT_SPACING
from prompt_toolkit.layout.dimension import to_dimension
from tui.catalog import ORDER
from tui.ui import Entry, KeyboardList, THEMES, STATUS_STYLES
from prompt_toolkit.styles import Style


class LayoutTests(unittest.TestCase):
    def test_responsive_panels_have_compact_fallback(self):
        app = DevboxTUI()
        for cols, rows, expected in [(120, 35, VSplit), (80, 35, HSplit), (58, 20, Window)]:
            with self.subTest(columns=cols, rows=rows):
                app.columns = lambda c=cols: c
                app.rows = lambda r=rows: r
                self.assertIsInstance(app._selection_layout(), expected)
        app.columns = lambda: 120
        self.assertIsInstance(app._home_layout(), VSplit)
        self.assertIsInstance(app._logs_layout(), VSplit)

    def test_right_panel_width_is_balanced_across_selection_changes(self):
        # All wide screens reserve half of the available columns for details.
        # A longer description or log path must wrap, not move the divider.
        app = DevboxTUI()
        app.columns = lambda: 120
        app.rows = lambda: 35

        for layout_getter, widget in (
            (app._home_layout, app.menu),
            (app._selection_layout, app.selector),
            (app._logs_layout, app.log_files),
        ):
            with self.subTest(layout=layout_getter.__name__):
                layout = layout_getter()
                self.assertIsInstance(layout, VSplit)
                panel = layout.children[-1]
                self.assertIsInstance(panel, Window)
                self.assertEqual(
                    (to_dimension(panel.width).min, to_dimension(panel.width).preferred,
                     to_dimension(panel.width).max),
                    (59,) * 3,
                )
                self.assertTrue(panel.wrap_lines())
                self.assertEqual(layout.padding, 1)

                # Simulate several cursor moves: neither pane is reconstructed
                # and content length must not alter the fixed panel dimension.
                for _ in range(min(5, len(widget.visible))):
                    widget.move(1)
                    self.assertIs(layout_getter(), layout)
                    self.assertIs(layout.children[-1], panel)
                    self.assertEqual(to_dimension(panel.width).preferred, 59)

    def test_wide_separator_does_not_shift_on_cursor_navigation(self):
        # Exercise prompt_toolkit's actual column allocator, not only the
        # declared Window dimension. Long details must never move the divider.
        app = DevboxTUI()
        app.open_menu("install")
        for columns in (94, 95, 120, 160, 200):
            app.columns = lambda c=columns: c
            app.rows = lambda: 35
            layout = app._selection_layout()
            divider_positions = []
            for key in ("zsh", "docker", "ponytail"):
                app.selector.index = next(
                    i for i, entry in enumerate(app.selector.visible)
                    if entry.key == key
                )
                screen = Screen(initial_width=columns, initial_height=24)
                layout.write_to_screen(
                    screen, MouseHandlers(),
                    WritePosition(0, 0, columns, 24),
                    parent_style="", erase_bg=True, z_index=None,
                )
                dividers = [
                    x for x, cell in screen.data_buffer[0].items()
                    if cell.char == "│"
                ]
                self.assertEqual(len(dividers), 1)
                divider_positions.append(dividers[0])
            with self.subTest(columns=columns):
                self.assertEqual(len(set(divider_positions)), 1)
                self.assertEqual(
                    divider_positions[0],
                    columns - detail_panel_width(columns) - 2,
                )

    def test_all_wide_panes_resize_without_rebuilding(self):
        app = DevboxTUI()
        app.columns = lambda: 120
        app.rows = lambda: 35
        layouts = [
            (app._home_layout, app.menu, lambda layout: layout),
            (app._selection_layout, app.selector, lambda layout: layout),
            (app._logs_layout, app.log_files, lambda layout: layout),
            (app._cleaner_layout, app.cleaner_list, lambda layout: layout.children[-1]),
        ]
        for getter, widget, split_of in layouts:
            app.columns = lambda: 120
            layout = getter()
            split = split_of(layout)
            panel = split.children[-1]
            for columns, expected_right in ((94, 46), (95, 46), (120, 59), (161, 79), (200, 99)):
                with self.subTest(view=getter.__name__, columns=columns):
                    app.columns = lambda c=columns: c
                    self.assertIs(getter(), layout)
                    self.assertIs(split_of(layout).children[-1], panel)
                    self.assertEqual(to_dimension(panel.width).preferred, expected_right)
                    self.assertEqual(widget.get_columns(), columns - expected_right - SPLIT_SPACING)
                    self.assertLessEqual(abs(widget.get_columns() - expected_right), 1)

    def test_balanced_panel_preserves_responsive_breakpoints(self):
        app = DevboxTUI()
        for columns, rows, selection_type, home_type, logs_type in (
            (94, 35, VSplit, VSplit, VSplit),
            (120, 35, VSplit, VSplit, VSplit),
            (80, 35, HSplit, HSplit, Window),
            (58, 20, Window, Window, Window),
        ):
            with self.subTest(columns=columns, rows=rows):
                app.columns = lambda c=columns: c
                app.rows = lambda r=rows: r
                self.assertIsInstance(app._selection_layout(), selection_type)
                self.assertIsInstance(app._home_layout(), home_type)
                self.assertIsInstance(app._logs_layout(), logs_type)

    def test_component_groups_appear_once_and_are_contiguous(self):
        app = DevboxTUI()
        app.open_menu("install")
        category_order = [entry.group for entry in app.selector.entries]
        self.assertEqual(
            [group for group in dict.fromkeys(category_order)],
            [group for group, _ in __import__(
                "tui.catalog", fromlist=["GROUPS"]
            ).GROUPS],
        )
        rendered = "".join(t for _, t in app.selector.render())
        self.assertEqual(rendered.count("  SHELL\n"), 1)
        self.assertEqual(rendered.count("  DEVELOPER TOOLS\n"), 1)

    def test_missing_status_is_highlighted_even_when_focused(self):
        noop = lambda: None
        widget = KeyboardList(
            [Entry("a", "First", status="Missing"), Entry("b", "Second", status="Missing")],
            on_enter=noop, on_back=noop, on_help=noop, on_change=noop,
        )
        fragments = widget.render()
        self.assertIn(("class:focus class:missing", "Missing\n"), fragments)
        self.assertIn(("class:missing", "Missing\n"), fragments)
        theme = Style.from_dict(THEMES["minimal"])
        normal = theme.get_attrs_for_style_str("class:missing")
        focused = theme.get_attrs_for_style_str("class:focus class:missing")
        self.assertEqual(normal.color, "ansibrightred")
        self.assertEqual(focused.color, normal.color)
        self.assertEqual(focused.bgcolor, "ansiblue")
        self.assertTrue(normal.bold)
        self.assertEqual(STATUS_STYLES["Unavailable"], "class:muted")
        mono = Style.from_dict(THEMES["mono"])
        self.assertTrue(mono.get_attrs_for_style_str("class:missing").underline)

    def test_status_aligns_to_list_pane_not_terminal(self):
        app = DevboxTUI()
        app.columns = lambda: 120
        app.open_menu("install")
        self.assertEqual(app.selector.get_columns(), 58)
        # Every displayed state begins at the same column, including focused
        # rows and entries with widely differing label lengths.
        rows = "".join(text for _, text in app.selector.render()).splitlines()
        states = ("Installed", "Missing", "Unverified")
        end_columns = [
            row.index(status) + len(status) for row in rows
            for status in states if status in row
        ]
        self.assertTrue(end_columns)
        self.assertEqual(len(set(end_columns)), 1)
        self.assertLess(max(len(row) for row in rows), app.selector.get_columns())

    def test_details_show_real_selection_and_inventory(self):
        app = DevboxTUI()
        app.columns = lambda: 120
        app.open_menu("install")
        app.selector.current_values = ["uv", "rtk"]
        app.selector.set_query("rtk")
        preview = "".join(text for _, text in app._component_details())
        self.assertIn("AGENT INTEGRATIONS", preview)
        self.assertNotIn("QUICK ACTIONS", preview)
        details = "".join(text for _, text in app._component_details(full=True))
        self.assertIn("OVERVIEW", details)
        self.assertIn("DESCRIPTION", details)
        self.assertIn("INVENTORY", details)
        self.assertIn(f"2 / {len(ORDER)} selected", details)
        self.assertIn("Selected: Yes", details)
        self.assertIn("QUICK ACTIONS", details)

    def test_visual_focus_differs_from_selected_items(self):
        app = DevboxTUI()
        app.open_menu("install")
        app.selector.current_values = ["zsh"]
        content = app.selector.render()
        text = "".join(fragment for _style, fragment in content)
        self.assertIn("  SHELL", text)
        self.assertIn("  DEVELOPER TOOLS", text)
        self.assertIn("[x] Zsh", text)
        self.assertIn("[ ] Powerlevel10k", text)
        self.assertTrue(any(style == "class:focus" for style, _text in content))
        app.selector.move(1)
        moved = app.selector.render()
        self.assertTrue(any(style == "class:checked" and "Zsh" in item for style, item in moved))
        self.assertIn("Requires: zsh", "".join(t for _, t in app._component_details()))

    def test_component_description_and_warnings_available(self):
        app = DevboxTUI()
        app.open_menu("install")
        app.selector.set_query("nvidia")
        current = app.selector.current
        self.assertEqual(current.key, "nvidia")
        details = "".join(fragment for _, fragment in app._component_details())
        self.assertIn("Requires: docker", details)
        self.assertIn("restart", details)

    def test_filter_clears_and_retains_order(self):
        app = DevboxTUI()
        app.open_menu("install")
        app.selector.set_query("pythON")
        self.assertEqual([x.key for x in app.selector.visible], ["uv"])
        app.selector.toggle()
        self.assertEqual(app.selector.current_values, ["uv"])
        app.selector.set_query("")
        self.assertEqual(len(app.selector.visible), len(ORDER))
        self.assertEqual(app.selector.current_values, ["uv"])

    def test_executing_without_percent_metric_uses_counts(self):
        app = DevboxTUI()
        app.current_action = "Install"
        app.status["fzf"] = "INSTALLED"
        app.status["uv"] = "RUNNING"
        progress = "".join(fragment for _, fragment in app._progress_tokens())
        self.assertIn("1 / 2 complete", progress)
        self.assertIn("Current: uv", progress)
        self.assertNotIn("%", progress)

    def test_theme_selection_is_reversible(self):
        with patch.dict(os.environ, {"DEVBOX_THEME": "mono"}):
            app = DevboxTUI()
        self.assertEqual(app.theme, "mono")
        app.toggle_theme()
        self.assertEqual(app.theme, "minimal")
        app.toggle_theme()
        self.assertEqual(app.theme, "mono")

    def test_history_labels_and_filter_are_useful(self):
        with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)):
            logs = Path(tmp) / "logs"
            logs.mkdir()
            (logs / "20261101-101020-install-a.log").write_text("installed uv\n")
            (logs / "20261101-111020-doctor-b.log").write_text("healthy\n")
            app = DevboxTUI()
            app.list_history()
            self.assertEqual(app.screen, "logs")
            self.assertEqual(len(app.log_files.visible), 2)
            first = app.log_files.visible[0]
            self.assertIn("Doctor", first.label)
            self.assertIn("2026-11-01", first.label)
            details = "".join(text for _, text in app._history_details())
            self.assertIn("healthy", details)
            app.log_files.set_query("install")
            self.assertEqual(len(app.log_files.visible), 1)
            self.assertIn("Install", app.log_files.current.label)

    def test_bulk_select_preserves_other_filtered_selections(self):
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        async def scenario():
            with create_pipe_input() as pipe:
                with create_app_session(input=pipe, output=DummyOutput()):
                    app = DevboxTUI()
                    task = asyncio.create_task(app.app.run_async())
                    try:
                        await asyncio.sleep(0.10)
                        pipe.send_text("jj\r\r")
                        await asyncio.sleep(0.10)
                        app.selector.current_values = ["uv"]
                        app.selector.set_query("Docker Engine")
                        self.assertEqual([x.key for x in app.selector.visible], ["docker"])
                        pipe.send_text("a")
                        await asyncio.sleep(0.12)
                        self.assertEqual(app.selector.current_values, ["uv", "docker"])
                        app.selector.set_query("no-matching-tool")
                        pipe.send_text("a")  # An empty filter must not remove hidden items.
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.selector.current_values, ["uv", "docker"])
                    finally:
                        if not task.done():
                            app.app.exit()
                            await asyncio.wait_for(task, 2)
        asyncio.run(scenario())

    def test_privileged_options_cannot_be_bulk_selected(self):
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        async def scenario():
            with create_pipe_input() as pipe:
                with create_app_session(input=pipe, output=DummyOutput()):
                    app = DevboxTUI()
                    task = asyncio.create_task(app.app.run_async())
                    try:
                        await asyncio.sleep(0.10)
                        pipe.send_text("jj\r\r")
                        await asyncio.sleep(0.10)
                        app.selector.current_values = ["zsh", "docker", "keychain"]
                        pipe.send_text("\r")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.screen, "confirm")
                        self.assertEqual(len(app.options.entries), 3)
                        pipe.send_text("a")  # No bulk approval on Confirm.
                        await asyncio.sleep(0.10)
                        self.assertFalse(app.options.current_values)
                        pipe.send_text(" ")
                        await asyncio.sleep(0.10)
                        self.assertEqual(len(app.options.current_values), 1)
                        pipe.send_text("n")  # No implicit clear/approval.
                        await asyncio.sleep(0.10)
                        self.assertEqual(len(app.options.current_values), 1)
                    finally:
                        if not task.done():
                            app.app.exit()
                            await asyncio.wait_for(task, 2)
        asyncio.run(scenario())

    def test_shared_confirmation_without_options_keyboard(self):
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        async def scenario():
            with create_pipe_input() as pipe:
                with create_app_session(input=pipe, output=DummyOutput()):
                    app = DevboxTUI()
                    task = asyncio.create_task(app.app.run_async())
                    try:
                        await asyncio.sleep(0.1)
                        pipe.send_text("jj\r\r")
                        await asyncio.sleep(0.1)
                        app.selector.current_values = ["fzf"]
                        pipe.send_text("\r")
                        await asyncio.sleep(0.1)
                        self.assertEqual(app.screen, "confirm")
                        self.assertFalse(app.dry_run)
                        self.assertTrue(app.app.layout.has_focus(app.confirm_plan))
                        self.assertIn("Enter Install", app._confirm_shortcuts())
                        pipe.send_text("d")
                        await asyncio.sleep(0.1)
                        self.assertTrue(app.dry_run)
                        self.assertIn("Enter Preview", app._confirm_shortcuts())
                        pipe.send_text("d")
                        await asyncio.sleep(0.1)
                        with patch.object(app, "start") as start:
                            pipe.send_text("\r")
                            await asyncio.sleep(0.1)
                            start.assert_called_once_with("install", ["fzf"])
                    finally:
                        if not task.done():
                            app.app.exit()
                            await asyncio.wait_for(task, 2)
        asyncio.run(scenario())

    def test_update_confirmation_has_no_preview_option(self):
        app = DevboxTUI()
        app.dry_run = True
        app.open_menu("update")
        self.assertFalse(app.dry_run)
        self.assertIn("Enter Update", app._confirm_shortcuts())
        self.assertNotIn("d Dry-run", app._confirm_shortcuts())

    def test_compact_footer_is_readable(self):
        app = DevboxTUI()
        for width in (58, 80, 120):
            app.columns = lambda w=width: w
            for screen in ("home", "select", "cleaner", "confirm", "run", "result", "logs"):
                with self.subTest(width=width, screen=screen):
                    page = app.views[screen]
                    footer_control = page.children[-1].content
                    segments = footer_control.text()
                    output = "".join(text for _, text in segments)
                    self.assertLessEqual(len(output), width - 2)
                    self.assertTrue(output.strip())

    def test_filter_escape_clears_before_leaving_history(self):
        with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)):
            logs = Path(tmp) / "logs"
            logs.mkdir()
            (logs / "20261101-111020-doctor-test.log").write_text("healthy\n")
            app = DevboxTUI()
            app.list_history()
            app.log_files.set_query("doctor")
            app.back()
            self.assertEqual(app.screen, "logs")
            self.assertEqual(app.log_files.query, "")
            app.back()
            self.assertEqual(app.screen, "home")

    def test_history_preview_is_cached_until_log_changes(self):
        from tui.app import _cached_log_tail
        with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)):
            logs = Path(tmp) / "logs"
            logs.mkdir()
            path = logs / "20261101-111020-doctor-test.log"
            path.write_text("first\n")
            app = DevboxTUI()
            app.list_history()
            _cached_log_tail.cache_clear()
            with patch("tui.app.log_tail", wraps=__import__(
                    "tui.backend", fromlist=["log_tail"]).log_tail) as read:
                app._history_details()
                app._history_details()
                self.assertEqual(read.call_count, 1)
                path.write_text("second version\n")
                app._history_details()
                self.assertEqual(read.call_count, 2)

    def test_idle_progress_poll_does_not_rewrite_unchanged_buffers(self):
        app = DevboxTUI()
        with patch.object(app, "_invalidate") as invalidate:
            app._refresh()
            first_status = app.status_view.text
            first_log = app.log_view.text
            initial_count = invalidate.call_count
            app._refresh()
            self.assertEqual(app.status_view.text, first_status)
            self.assertEqual(app.log_view.text, first_log)
            self.assertEqual(invalidate.call_count, initial_count)

    def test_layout_instances_remain_stable_between_redraws(self):
        app = DevboxTUI()
        app.columns = lambda: 120
        app.rows = lambda: 35

        home = app._home_layout()
        selection = app._selection_layout()
        logs = app._logs_layout()
        run = app._run_layout()
        self.assertIs(home, app._home_layout())
        self.assertIs(selection, app._selection_layout())
        self.assertIs(logs, app._logs_layout())
        self.assertIs(run, app._run_layout())

        app.open_menu("install")
        refreshed_selection = app._selection_layout()
        self.assertIsNot(selection, refreshed_selection)
        self.assertIs(refreshed_selection.children[0], app.selector.window)

        app.selector.current_values = ["zsh"]
        old_confirm = app._confirm_layout()
        app.confirm_selection()
        new_confirm = app._confirm_layout()
        self.assertIsNot(old_confirm, new_confirm)
        self.assertIs(new_confirm.children[-1], app.options.window)

        with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)):
            app.list_history()
        refreshed_logs = app._logs_layout()
        self.assertIsNot(logs, refreshed_logs)
        self.assertIs(refreshed_logs.children[0], app.log_files.window)

    def test_compact_info_and_keyboard_search(self):
        async def scenario():
            with create_pipe_input() as pipe:
                with create_app_session(input=pipe, output=DummyOutput()):
                    app = DevboxTUI()
                    app.columns = lambda: 58
                    app.rows = lambda: 20
                    task = asyncio.create_task(app.app.run_async())
                    try:
                        await asyncio.sleep(0.10)
                        pipe.send_text("jj\r\r")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.screen, "select")
                        self.assertIsInstance(app._selection_layout(), Window)

                        pipe.send_text("i")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.screen, "info")
                        self.assertIn("Zsh", app.info_view.text)
                        pipe.send_text("\x1b")
                        await asyncio.sleep(0.30)
                        self.assertEqual(app.screen, "select")

                        pipe.send_text("/")
                        await asyncio.sleep(0.10)
                        self.assertTrue(app.filter_active)
                        pipe.send_text("fzf")
                        await asyncio.sleep(0.10)
                        self.assertEqual([x.key for x in app.selector.visible], ["fzf"])
                        pipe.send_text("\r")
                        await asyncio.sleep(0.10)
                        self.assertFalse(app.filter_active)
                        pipe.send_text(" ")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.selector.current_values, ["fzf"])
                        pipe.send_text("\r")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.screen, "confirm")
                        pipe.send_text("\x1b")
                        await asyncio.sleep(0.30)
                        self.assertEqual(app.screen, "select")
                        self.assertEqual(app.selector.query, "fzf")
                        pipe.send_text("\x1b")
                        await asyncio.sleep(0.30)
                        self.assertEqual(app.screen, "select")
                        self.assertEqual(app.selector.query, "")
                        pipe.send_text("\x1b")
                        await asyncio.sleep(0.30)
                        self.assertEqual(app.screen, "toolkit")
                        self.assertEqual(app.toolkit_category, "Environment")
                        pipe.send_text("\x1b")
                        await asyncio.sleep(0.30)
                        self.assertEqual(app.screen, "home")
                        pipe.send_text("q")
                        await asyncio.wait_for(task, 2)
                    finally:
                        if not task.done():
                            app.app.exit()
                            await asyncio.wait_for(task, 2)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
