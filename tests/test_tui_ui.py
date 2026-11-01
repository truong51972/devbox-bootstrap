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
from prompt_toolkit.output import DummyOutput

from tui.app import DevboxTUI
from tui.ui import Entry, KeyboardList


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

    def test_visual_focus_differs_from_selected_items(self):
        app = DevboxTUI()
        app.open_menu()
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
        app.open_menu()
        app.selector.set_query("nvidia")
        current = app.selector.current
        self.assertEqual(current.key, "nvidia")
        details = "".join(fragment for _, fragment in app._component_details())
        self.assertIn("Requires: docker", details)
        self.assertIn("restart", details)

    def test_filter_clears_and_retains_order(self):
        app = DevboxTUI()
        app.open_menu()
        app.selector.set_query("pythON")
        self.assertEqual([x.key for x in app.selector.visible], ["uv"])
        app.selector.toggle()
        self.assertEqual(app.selector.current_values, ["uv"])
        app.selector.set_query("")
        self.assertEqual(len(app.selector.visible), 13)
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
                        pipe.send_text("\r")
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
                        pipe.send_text("\r")
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

    def test_compact_footer_is_readable(self):
        app = DevboxTUI()
        for width in (58, 80, 120):
            app.columns = lambda w=width: w
            for screen in ("home", "select", "confirm", "run", "result", "logs"):
                with self.subTest(width=width, screen=screen):
                    page = app.views[screen]
                    footer_control = page.children[-1].content
                    segments = footer_control.text()
                    output = "".join(text for _, text in segments)
                    self.assertLessEqual(len(output), width - 2)
                    self.assertTrue(output.strip())

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

        app.open_menu()
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
                        pipe.send_text("\r")
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
