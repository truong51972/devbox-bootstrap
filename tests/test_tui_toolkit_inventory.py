"""Structured inventory presentation and navigation regression tests."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from prompt_toolkit.layout import VSplit
from prompt_toolkit.layout.dimension import to_dimension

from tui.agent_status import PluginStatus
from tui.app import DevboxTUI
from tui.toolkit.inventory_models import ToolRow, AgentRow, AgentMatrix
from tui.toolkit.inventory_view import detail_fragments
from tui.ui import STATUS_STYLES
from tui.views import detail_panel_width


TOOLS = (
    ToolRow("uv", "uv (Python)", "DEVELOPER TOOLS", "Installed", "/home/user/.local/bin/uv", "Manager not verified"),
    ToolRow("jq", "jq", "DEVELOPER TOOLS", "Missing", "", "No executable detected"),
    ToolRow("docker", "Docker Engine", "CONTAINERS", "Partial", "/usr/bin/docker", "Ownership not verified"),
)


def plugin(agent, state, source="CLI inventory", reason="Registration evidence"):
    return PluginStatus(agent, state, source, reason)


MATRIX = AgentMatrix(plugin("rtk", "Installed"), (
    AgentRow("codex", "Codex", "Available", "/usr/bin/codex",
             plugin("codex", "Installed", "instructions", "Rules only"),
             plugin("codex", "Installed")),
    AgentRow("claude", "Claude Code", "Available", "/usr/bin/claude",
             plugin("claude", "Missing", reason="Hook not configured"),
             plugin("claude", "Unverified")),
    AgentRow("gemini", "Gemini CLI", "Unavailable", "",
             plugin("gemini", "Unavailable"), plugin("gemini", "Unavailable")),
))


def text(fragments):
    return "".join(value for _, value in fragments)


class InventoryTests(unittest.TestCase):
    def test_tool_state_styles_and_group_cursor(self):
        app = DevboxTUI()
        app.columns = lambda: 120
        widget = app.inventory_list
        widget.set_snapshot(TOOLS)
        rendered = widget.render()
        self.assertIn(("class:missing", "Missing".ljust(13)), rendered)
        self.assertIn(("class:warning", "Partial".ljust(13)), rendered)
        self.assertIn("DEVELOPER TOOLS", text(rendered))
        widget.move(2)
        row = text(widget.render()).splitlines()[widget.cursor_position().y]
        self.assertTrue(row.startswith("> Docker Engine"))
        self.assertTrue(row.rstrip().endswith("Partial"))
        details = detail_fragments(TOOLS[2])
        self.assertIn("Ownership not verified", text(details))
        self.assertIn("Detection is not a runtime health check", text(details))

    def test_agent_matrix_columns_have_semantic_colors_at_all_sizes(self):
        app = DevboxTUI()
        widget = app.inventory_list
        widget.set_snapshot(MATRIX)
        for columns in (58, 80, 94, 120, 160):
            with self.subTest(columns=columns):
                app.columns = lambda c=columns: c
                rendered = widget.render()
                plain = text(rendered)
                self.assertIn("CLI", plain)
                self.assertIn("RTK", plain)
                self.assertIn("Rules", plain)
                self.assertTrue(any(style == "class:missing" and "Missing" in value for style, value in rendered))
                self.assertTrue(any(style == "class:warning" for style, value in rendered))
                self.assertTrue(all(len(line) <= app.inventory_columns() for line in plain.splitlines()))
        self.assertEqual(STATUS_STYLES["Unavailable"], "class:muted")
        self.assertIn("Hook not configured", text(detail_fragments(MATRIX.agents[1])))

    def test_wide_layout_has_stable_split(self):
        app = DevboxTUI()
        app.columns = lambda: 120
        app.inventory_list.set_snapshot(MATRIX)
        layout = app.inventory_layout()
        self.assertIsInstance(layout, VSplit)
        self.assertEqual(to_dimension(layout.children[-1].width).preferred, detail_panel_width(120))
        app.inventory_list.move(1)
        self.assertIs(layout, app.inventory_layout())
        app.columns = lambda: 58
        self.assertIs(app.inventory_layout(), app.inventory_list.window)

    def test_structured_result_filter_refresh_and_back(self):
        async def exercise():
            app = DevboxTUI()
            app.open_toolkit("Environment")
            app.toolkit_list.set_query("development tool inventory")
            with patch("tui.toolkit.screens.environment.tool_rows", return_value=TOOLS):
                app.toolkit_open_action()
                await app.toolkit_task
                self.assertEqual(app.screen, "toolkit_tools")
                self.assertIs(app._active_list(), app.inventory_list)
                app.inventory_list.set_query("jq")
                self.assertEqual(app.inventory_list.current_value, "jq")
                app.inventory_refresh()
                await app.toolkit_task
                self.assertEqual(app.inventory_list.current_value, "jq")
                app.inventory_show_detail()
                self.assertEqual(app.screen, "toolkit_inventory_detail")
                self.assertIn("No executable detected", app.inventory_detail.text)
                app.back()
                self.assertEqual(app.screen, "toolkit_tools")
                app.back()
                self.assertEqual(app.inventory_list.query, "")
                app.back()
                self.assertEqual(app.screen, "toolkit")
                self.assertIsNone(app.log_path)
        asyncio.run(exercise())

    def test_agent_matrix_result_uses_structured_snapshot(self):
        async def exercise():
            app = DevboxTUI()
            app.open_toolkit("Coding Agents")
            app.toolkit_list.set_query("integration matrix")
            with patch("tui.toolkit.screens.agents.agent_matrix", return_value=MATRIX):
                app.toolkit_open_action()
                await app.toolkit_task
                self.assertEqual(app.screen, "toolkit_matrix")
                self.assertIs(app.inventory_list.matrix, MATRIX)
                self.assertIn("Registration only", text(app.inventory_preview()))
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
