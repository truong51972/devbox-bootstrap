"""Regression coverage for guided toolkit interaction and structured results."""
import asyncio
import io
import unittest
from unittest.mock import patch

from tui.app import DevboxTUI
from tui.toolkit import collectors
from tui.toolkit.cli import main
from tui.toolkit.guidance import GUIDES, MODULES
from tui.toolkit.registry import ACTIONS
from tui.toolkit.results import TableData, table
from tui.toolkit.ux import validate_form
from tui.toolkit.result_view import fragments


def select(app, category, key):
    app.open_toolkit(category)
    app.toolkit_list.index = next(i for i, item in enumerate(app.toolkit_list.visible) if item.key == key)
    app.toolkit_open_action()


def plain(fragments):
    return "".join(text for _, text in fragments)


class ToolkitUXTests(unittest.TestCase):
    def test_guidance_complete_and_cli_help(self):
        for action in ACTIONS:
            with self.subTest(action=action.id):
                self.assertIn(action.id, GUIDES)
                self.assertTrue(action.guide.use and action.guide.result and action.guide.limit)
                self.assertIn(action.category, MODULES)
                if action.required:
                    self.assertNotEqual(action.guide.kind, "none")
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(main(["net", "tcp", "--help"]), 0)
            self.assertIn("localhost:5432", out.getvalue())

    def test_form_validation(self):
        self.assertEqual(validate_form("net.port", " 8000 "), "8000")
        self.assertEqual(validate_form("net.tcp", "[::1]:5432"), "[::1]:5432")
        self.assertEqual(validate_form("agent.skills", ""), "")
        for key, value in (("net.port", "0"), ("net.tcp", "host:99999"), ("net.http", "ftp://host"), ("agent.version", "unknown"), ("sys.terminate", "1")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_form(key, value)

    def test_contextual_help_and_single_line_input(self):
        app = DevboxTUI()
        app.open_toolkit("Networking")
        app.toolkit_list.set_query("find process by port")
        app._show_help()
        self.assertIn("COMMON TASKS", app.help_view.text)
        self.assertIn("8000", app.help_view.text)
        app.back()
        self.assertEqual(app.screen, "toolkit")
        app.toolkit_open_action()
        self.assertEqual(app.screen, "toolkit_input")
        self.assertFalse(app.ux_editor)
        app.ux_line.text = "99999"
        app.toolkit_submit()
        self.assertIsNone(app.toolkit_task)
        self.assertEqual(app.screen, "toolkit_input")

    def test_http_error_semantics(self):
        with patch("tui.toolkit.collectors.network.http", return_value="HTTP 503\nRemote 192.0.2.1\nTotal 0.1s"):
            result = collectors.collect("net.http", "https://example.com", ".")
        self.assertEqual(result.tone, "error")
        self.assertIn("503", plain(fragments(result)))

    def test_listeners_unknown_owners_and_empty(self):
        with patch("tui.toolkit.collectors.native", return_value="tcp LISTEN 0 128 127.0.0.1:8000 0.0.0.0:*"):
            result = collectors.collect("net.ports", "", ".")
        self.assertIsInstance(result.data, TableData)
        self.assertEqual(result.data.rows[0][0].value, "8000")
        self.assertEqual(result.data.rows[0][-1].value, "Unknown")
        with patch("tui.toolkit.collectors.native", return_value="(no output)"):
            self.assertEqual(collectors.collect("net.ports", "", ".").data.rows, ())

    def test_editor_keeps_input_until_back(self):
        async def exercise():
            app = DevboxTUI()
            select(app, "Utilities", "util.json-format")
            self.assertTrue(app.ux_editor)
            app.toolkit_input.text = '{"hello":"world"}'
            app.toolkit_submit()
            await app.toolkit_task
            self.assertEqual(app.screen, "toolkit_input")
            self.assertIn('"hello": "world"', app.ux_editor_output.text)
            self.assertIn("hello", app.toolkit_input.text)
            app.back()
            self.assertEqual(app.toolkit_input.text, "")
            self.assertEqual(app.ux_editor_output.text, "")
            self.assertIsNone(app.log_path)
        asyncio.run(exercise())

    def test_table_navigation_related_target_and_refresh(self):
        async def exercise():
            app = DevboxTUI()
            snapshot = table(("ID", "Name", "State"), [("a" * 64, "api", "running"), ("b" * 64, "db", "exited")], "2 containers")
            with patch("tui.toolkit.screens.collect", return_value=snapshot):
                select(app, "Containers", "docker.ps")
                await app.toolkit_task
                self.assertEqual(app.screen, "toolkit_table")
                app.ux_table.set_query("db")
                self.assertEqual(app.ux_table.row[1].value, "db")
                app.ux_repeat()
                await app.toolkit_task
                self.assertEqual(app.ux_table.query, "db")
                self.assertEqual(app.ux_table.row[1].value, "db")
                app.ux_open_related()
                self.assertEqual(app.screen, "toolkit_related")
                app.ux_related.index = next(i for i, item in enumerate(app.ux_related.visible) if item.key == "docker.restart")
                app.ux_run_related()
                self.assertEqual(app.screen, "toolkit_input")
                self.assertEqual(app.ux_line.text, "b" * 64)
                app.back()
                self.assertEqual(app.screen, "toolkit_table")
                self.assertEqual(app.ux_table.query, "db")
        asyncio.run(exercise())

    def test_table_width_and_semantic_state(self):
        app = DevboxTUI()
        result = table(("Name", "State", "PID", "Address"), [("server", collectors.Cell("Missing", "missing"), "10", "127.0.0.1")])
        app.ux_table.set_data(result.data)
        for width in (58, 80, 120, 160):
            app.columns = lambda w=width: w
            rendered = app.ux_table.render()
            self.assertTrue(all(len(line) <= width for line in plain(rendered).splitlines()))
            self.assertTrue(any("class:missing" in style for style, _ in rendered))


if __name__ == "__main__":
    unittest.main()
