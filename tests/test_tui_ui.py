"""Visual/layout and keyboard interaction regressions for the minimal TUI."""
from __future__ import annotations

import asyncio
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
                        await asyncio.sleep(0.16)
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
                        await asyncio.sleep(0.16)
                        self.assertEqual(app.screen, "select")
                        pipe.send_text("\x1b")
                        await asyncio.sleep(0.16)
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
