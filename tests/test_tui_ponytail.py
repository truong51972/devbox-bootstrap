"""Regression tests for read-only Ponytail agent inventory and aggregation."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tui import agent_status
from tui.catalog import inventory


class PonytailStatusTests(unittest.TestCase):
    def test_claude_json_detects_enabled_and_disabled(self):
        self.assertEqual(agent_status._from_json("claude", json.dumps([
            {"id": "other@misc", "enabled": True},
            {"id": "ponytail@ponytail", "enabled": True},
        ])), "Installed")
        self.assertEqual(agent_status._from_json("claude", json.dumps([
            {"id": "ponytail@ponytail", "enabled": False},
        ])), "Disabled")

    def test_codex_only_checks_installed_not_available(self):
        self.assertEqual(agent_status._from_json("codex", json.dumps({
            "installed": [],
            "available": [{"pluginId": "ponytail@ponytail", "enabled": True}],
        })), "Missing")
        self.assertEqual(agent_status._from_json("codex", json.dumps({
            "installed": [{"pluginId": "ponytail@ponytail",
                           "enabled": True, "installed": True}],
        })), "Installed")
        self.assertEqual(agent_status._from_json("codex", json.dumps({
            "installed": [{"pluginId": "ponytail@ponytail",
                           "enabled": False, "installed": True}],
        })), "Disabled")

    def test_copilot_json_and_broken_output(self):
        self.assertEqual(agent_status._from_json("copilot", json.dumps([
            {"name": "ponytail", "enabled": True}
        ])), "Installed")
        self.assertEqual(agent_status._from_json("copilot", "not json"), "Unverified")
        self.assertEqual(agent_status._from_json("codex", json.dumps({
            "available": [{"name": "ponytail"}]
        })), "Unverified")

    def test_text_inventory_and_exact_plugin_name(self):
        self.assertEqual(agent_status._from_text(
            "Installed plugins:\n@dietrichgebert/ponytail (latest)\n"
        ), "Installed")
        self.assertEqual(agent_status._from_text(
            "ponytail (disabled)\n"
        ), "Disabled")
        self.assertEqual(agent_status._from_text(
            "other-ponytail-utils 1.0\n"
        ), "Missing")
        self.assertEqual(agent_status._from_text(
            "No extensions installed\n"
        ), "Missing")

    def test_probe_rejects_missing_cli_and_failed_commands(self):
        with patch("tui.agent_status.shutil.which", return_value=None):
            self.assertEqual(agent_status.probe_agent("codex"), "Unverified")
        with patch("tui.agent_status.shutil.which", return_value="/bin/codex"), \
             patch("tui.agent_status.subprocess.run", return_value=SimpleNamespace(
                 returncode=1, stdout=""
             )):
            self.assertEqual(agent_status.probe_agent("codex"), "Unverified")

    def test_probe_receipts_are_not_equivalent_to_plugin_health(self):
        with TemporaryDirectory() as temp:
            state = Path(temp)
            (state / "ponytail-codex").write_text("2026-11-18")
            (state / "ponytail-claude").write_text("2026-11-18")
            (state / "ponytail-unknown").write_text("2026-11-18")
            statuses = {"codex": "Installed", "claude": "Unverified"}
            with patch("tui.agent_status.probe_agent",
                       side_effect=lambda agent: statuses[agent]) as probe:
                result = agent_status.probe_ponytail(state)
            self.assertEqual(
                result, {"claude": "Unverified", "codex": "Installed"}
            )
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(agent_status.summary(result), "Partial")

    def test_summary_states(self):
        cases = [
            ({}, "Missing"),
            ({"codex": "Installed"}, "Installed"),
            ({"codex": "Installed", "claude": "Installed"}, "Installed"),
            ({"codex": "Installed", "claude": "Missing"}, "Partial"),
            ({"codex": "Installed", "claude": "Unverified"}, "Partial"),
            ({"codex": "Disabled"}, "Disabled"),
            ({"codex": "Missing"}, "Missing"),
            ({"codex": "Unverified"}, "Unverified"),
            ({"codex": "Disabled", "claude": "Unverified"}, "Unverified"),
        ]
        for states, expected in cases:
            with self.subTest(states=states):
                self.assertEqual(agent_status.summary(states), expected)

    def test_inventory_uses_live_plugin_state_not_receipt(self):
        with patch("tui.catalog.installed", return_value=False):
            result = inventory({"codex": "Installed"})
            self.assertEqual(result["ponytail"], "Installed")
            result = inventory({"codex": "Unverified"})
            self.assertEqual(result["ponytail"], "Unverified")
            result = inventory({"codex": "Disabled"})
            self.assertEqual(result["ponytail"], "Disabled")


if __name__ == "__main__":
    unittest.main()
