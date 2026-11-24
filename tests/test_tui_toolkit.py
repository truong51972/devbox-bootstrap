"""Shared CLI/TUI convenience actions and mutation safety contracts."""
import asyncio
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from tui.app import DevboxTUI
from tui.toolkit import data, network, operations, registry, settings, workflows
from tui.toolkit.cli import main


class ToolkitTests(unittest.TestCase):
    def test_unique_actions_and_local_transforms(self):
        self.assertEqual(len(registry.ACTIONS), len(registry.BY_ID))
        self.assertEqual(json.loads(registry.execute("util.json-format", '{"x":1}', ".")), {"x": 1})
        self.assertEqual(registry.execute("util.base64-decode", "aGVsbG8=", "."), "hello")
        value = uuid.UUID(registry.execute("util.uuid7", "", "."))
        self.assertEqual(value.version, 7)
        self.assertEqual(value.variant, uuid.RFC_4122)

    def test_port_and_endpoint_validation(self):
        for value in ("0", "65536", "-1", "80;id", ""):
            with self.assertRaises(ValueError):
                network.port_number(value)
        self.assertEqual(network.endpoint("[::1]:443"), ("::1", 443))
        with self.assertRaises(ValueError):
            network.endpoint("user:pass@host:443")

    def test_cli_reads_data_from_stdin(self):
        with patch("sys.stdin", io.StringIO('{"a":1}')), patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(main(["util", "json", "format"]), 0)
            self.assertEqual(json.loads(out.getvalue()), {"a": 1})

    def test_managed_actions_preview_only_without_yes(self):
        plan = operations.Plan("docker.stop", "api", "a" * 64, "Stop api", "unix:///tmp/docker.sock")
        with patch("tui.toolkit.cli.prepare", return_value=plan), patch("tui.toolkit.cli.apply") as apply, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main(["docker", "stop", "api"]), 0)
            apply.assert_not_called()

    def test_workflow_registration_and_favorite_persistence(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            self.assertTrue(settings.toggle_favorite("net.ports"))
            self.assertEqual(settings.favorites(), ["net.ports"])
            self.assertFalse(settings.toggle_favorite("net.ports"))
            path = settings.config_dir() / "actions.json"
            path.write_text(json.dumps([{"id":"sample","command":["echo","hello"]}]))
            self.assertEqual(workflows.list_workflows()["sample"].command, ("echo", "hello"))
            path.write_text(json.dumps([{"id":"btop","command":["echo","x"]}]))
            with self.assertRaises(ValueError):
                workflows.list_workflows()

    def test_tui_navigation_and_filter(self):
        app = DevboxTUI()
        app.open_toolkit("Networking")
        self.assertEqual(app.screen, "toolkit")
        app.toolkit_list.set_query("listening")
        self.assertEqual(app.toolkit_list.current_value, "net.ports")
        app.back()
        self.assertEqual(app.toolkit_list.query, "")
        app.back()
        self.assertEqual(app.screen, "home")

    def test_tui_query_runs_without_logging(self):
        async def exercise():
            app = DevboxTUI()
            app.open_toolkit("Utilities")
            app.toolkit_list.set_query("generate uuid v4")
            app.toolkit_open_action()
            await app.toolkit_task
            self.assertEqual(uuid.UUID(app.toolkit_result.text).version, 4)
            self.assertIsNone(app.log_path)
            app.back()
            self.assertEqual(app.toolkit_result.text, "")
        asyncio.run(exercise())

    def test_process_termination_refuses_protected_pid(self):
        with self.assertRaises(ValueError):
            operations.prepare("sys.terminate", "1", ".")


if __name__ == "__main__":
    unittest.main()
