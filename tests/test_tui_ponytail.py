"""Ponytail agent inventory: correctness, discovery and TUI responsiveness."""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tui import agent_status
from tui.app import DevboxTUI
from tui.catalog import inventory


class PonytailStatusTests(unittest.TestCase):
    def test_claude_json_enabled_disabled_and_errors(self):
        self.assertEqual(agent_status._from_json("claude", json.dumps([
            {"id": "ponytail@ponytail", "enabled": True}
        ])), "Installed")
        self.assertEqual(agent_status._from_json("claude", json.dumps([
            {"id": "ponytail@ponytail", "enabled": False}
        ])), "Disabled")
        self.assertEqual(agent_status._from_json("claude", json.dumps([
            {"id": "ponytail@ponytail", "enabled": True,
             "errors": ["plugin failed to load"]}
        ])), "Unverified")

    def test_codex_available_marketplace_is_not_installed(self):
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

    def test_copilot_json_supports_current_and_previous_shapes(self):
        for payload in (
            [{"name": "ponytail", "enabled": True}],
            {"plugins": [{"name": "ponytail", "enabled": True}]},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    agent_status._from_json("copilot", json.dumps(payload)),
                    "Installed",
                )
        self.assertEqual(agent_status._from_json("copilot", "{oops"), "Unverified")
        self.assertEqual(agent_status._from_json("codex", json.dumps({
            "available": [{"name": "ponytail"}]
        })), "Unverified")

    def test_opencode_and_gemini_text_flags(self):
        self.assertEqual(agent_status._from_text(
            "Installed plugins:\n@dietrichgebert/ponytail (latest)\n"
        ), "Installed")
        self.assertEqual(agent_status._from_text(
            "ponytail (disabled)\n"
        ), "Disabled")
        self.assertEqual(agent_status._from_text(
            "other-ponytail-utils 1.0\n"
        ), "Missing")
        output = (
            "✓ ponytail (5.0)\n"
            "  Path: /home/user/.gemini/extensions/ponytail\n"
            "  Enabled (User): true\n"
            "  Enabled (Workspace): false\n"
        )
        self.assertEqual(agent_status._from_text(output, gemini=True), "Installed")
        self.assertEqual(agent_status._from_text(
            output.replace("Enabled (User): true", "Enabled (User): false"),
            gemini=True,
        ), "Disabled")
        self.assertEqual(
            agent_status._from_text("✓ ponytail\n", gemini=True), "Unverified"
        )

    def test_gemini_flags_do_not_leak_between_records(self):
        output = ("✓ ponytail (5.0)\n"
                  "  Enabled (User): false\n"
                  "  Enabled (Workspace): false\n"
                  "✓ another-extension (1.0)\n"
                  "  Enabled (User): true\n"
                  "  Enabled (Workspace): true\n")
        self.assertEqual(agent_status._from_text(output, gemini=True), "Disabled")

    def test_unknown_inventory_and_exact_identity(self):
        self.assertEqual(agent_status._from_text(""), "Unverified")
        self.assertEqual(agent_status._from_text("Warning: ponytail is available"), "Unverified")
        self.assertEqual(agent_status._from_json("codex", '{"installed":[{}]}'), "Unverified")
        self.assertEqual(agent_status._from_json("codex", '{"installed":[{"id":"other@ponytail"}]}'), "Missing")
        self.assertEqual(agent_status._from_json("claude", '[{"id":"ponytail@ponytail","enabled":"false"}]'), "Unverified")

    def test_diagnostics_and_retry(self):
        import subprocess
        with patch("tui.agent_status.shutil.which", return_value="/bin/codex"), \
             patch("tui.agent_status.subprocess.run", side_effect=[
                 subprocess.TimeoutExpired("codex", 6),
                 SimpleNamespace(returncode=0, stdout='{"installed":[{"id":"ponytail@ponytail"}]}'),
             ]) as run:
            result = agent_status.probe_agent_detail("codex")
            self.assertEqual(result.state, "Installed")
            self.assertEqual(run.call_count, 2)
        with patch("tui.agent_status.shutil.which", return_value="/bin/codex"), \
             patch("tui.agent_status.subprocess.run", return_value=SimpleNamespace(
                 returncode=2, stdout="", stderr="unsupported --json"
             )):
            result = agent_status.probe_agent_detail("codex")
            self.assertEqual(result.state, "Unverified")
            self.assertIn("unsupported --json", result.reason)

    def test_legacy_opencode_config(self):
        import os
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": temp, "OPENCODE_CONFIG": ""}), \
             patch("tui.agent_status.shutil.which", return_value="/bin/opencode"), \
             patch("tui.agent_status.subprocess.run", return_value=SimpleNamespace(
                 returncode=1, stdout="", stderr="unknown command"
             )):
            config = Path(temp) / "opencode"
            config.mkdir()
            (config / "opencode.jsonc").write_text(
                '{// comment\n"plugin":["@dietrichgebert/ponytail@latest",],}', encoding="utf-8"
            )
            result = agent_status.probe_agent_detail("opencode")
            self.assertEqual(result.state, "Installed")
            self.assertEqual(result.source, "local config")

    def test_discovery_lists_all_agents_without_receipts(self):
        detected = {"claude", "codex", "opencode"}
        with patch("tui.agent_status.shutil.which",
                   side_effect=lambda name: "/bin/" + name if name in detected else None):
            statuses = agent_status.discover_agents()
        self.assertEqual(list(statuses), list(agent_status.AGENTS))
        self.assertEqual(statuses["claude"], "Checking")
        self.assertEqual(statuses["codex"], "Checking")
        self.assertEqual(statuses["opencode"], "Checking")
        self.assertEqual(statuses["gemini"], "Unavailable")
        self.assertEqual(statuses["copilot"], "Unavailable")

    def test_failed_or_unsupported_queries_never_claim_missing(self):
        with patch("tui.agent_status.shutil.which", return_value=None):
            self.assertEqual(agent_status.probe_agent("codex"), "Unavailable")
        with patch("tui.agent_status.shutil.which", return_value="/bin/codex"), \
             patch("tui.agent_status.subprocess.run", return_value=SimpleNamespace(
                 returncode=1, stdout=""
             )):
            self.assertEqual(agent_status.probe_agent("codex"), "Unverified")
        with patch("tui.agent_status.shutil.which", return_value="/bin/codex"), \
             patch("tui.agent_status.subprocess.run",
                   side_effect=__import__("subprocess").TimeoutExpired("codex", 2)):
            self.assertEqual(agent_status.probe_agent("codex"), "Unverified")

    def test_summary_ignores_missing_cli_but_not_missing_plugins(self):
        scenarios = [
            ({}, "Missing"),
            ({"codex": "Unavailable"}, "Missing"),
            ({"codex": "Installed", "claude": "Unavailable"}, "Installed"),
            ({"codex": "Checking", "claude": "Unavailable"}, "Checking"),
            ({"codex": "Installed", "claude": "Checking"}, "Checking"),
            ({"codex": "Installed", "claude": "Missing"}, "Partial"),
            ({"codex": "Installed", "claude": "Disabled"}, "Partial"),
            ({"codex": "Missing", "claude": "Unavailable"}, "Missing"),
            ({"codex": "Unverified", "claude": "Missing"}, "Unverified"),
            ({"codex": "Disabled", "claude": "Missing"}, "Disabled"),
        ]
        for values, expected in scenarios:
            with self.subTest(values=values):
                self.assertEqual(agent_status.summary(values), expected)

    def test_quick_inventory_does_not_run_rtk_command(self):
        with patch("tui.catalog.installed", return_value=False) as installed, \
             patch("tui.catalog.executable", return_value=True):
            result = inventory({"codex": "Checking"}, quick=True)
        self.assertEqual(result["rtk"], "Unverified")
        self.assertEqual(result["ponytail"], "Checking")
        self.assertNotIn("rtk", [call.args[0] for call in installed.call_args_list])

    def test_constructor_does_not_probe_any_cli(self):
        with patch("tui.app.probe_agent",
                   side_effect=AssertionError("Probe on event loop")), \
             patch("tui.catalog.subprocess.run",
                   side_effect=AssertionError("Blocking inventory")):
            app = DevboxTUI()
            self.assertIsNotNone(app)
            app.open_menu()
            self.assertEqual(app.screen, "select")

    def test_async_scans_all_detected_agents_and_manual_refresh(self):
        detected = {
            "claude": "Checking", "codex": "Checking",
            "copilot": "Unavailable", "opencode": "Unavailable",
            "gemini": "Unavailable",
        }
        calls = []

        def slow_probe(agent):
            calls.append(agent)
            time.sleep(0.25)
            return agent_status.PluginStatus(agent, "Installed" if agent == "claude" else "Missing", "test", "fixture")

        async def scenario():
            with patch("tui.app.discover_agents", side_effect=lambda: detected.copy()), \
                 patch("tui.app.probe_agent", side_effect=slow_probe), \
                 patch("tui.app.installed", return_value=False):
                app = DevboxTUI()
                start = time.monotonic()
                app.open_menu()
                duration = time.monotonic() - start
                # Old code would block for an entire CLI timeout here.
                self.assertLess(duration, 0.20)
                self.assertEqual(app.available["ponytail"], "Checking")
                self.assertEqual(app.screen, "select")
                await asyncio.wait_for(app._agent_scan_task, timeout=2)
                self.assertEqual(app.ponytail_agents["claude"], "Installed")
                self.assertEqual(app.ponytail_agents["codex"], "Missing")
                self.assertEqual(app.available["ponytail"], "Partial")
                self.assertEqual(app.selector.entries[-1].status, "Partial")

                app._schedule_agent_scan()  # Recent result is cached.
                self.assertEqual(len(calls), 2)

                app._refresh_agent_status()
                await asyncio.wait_for(app._agent_scan_task, timeout=2)
                self.assertEqual(len(calls), 4)

                app.selector.set_query("ponytail")
                details = "".join(t for _, t in app._component_details(full=True))
                self.assertIn("Claude Code", details)
                self.assertIn("Codex", details)
                self.assertIn("Copilot CLI", details)
                self.assertIn("Installed", details)
                self.assertIn("Missing", details)
                self.assertIn("Unavailable", details)

        asyncio.run(scenario())

    def test_install_invalidation_discards_stale_in_flight_result(self):
        detected = {
            "claude": "Checking", "codex": "Unavailable",
            "copilot": "Unavailable", "opencode": "Unavailable",
            "gemini": "Unavailable",
        }

        def delayed_agent(_agent):
            time.sleep(0.15)
            return agent_status.PluginStatus(_agent, "Installed", "test", "fixture")

        async def scenario():
            with patch("tui.app.discover_agents",
                       side_effect=lambda: detected.copy()), \
                 patch("tui.app.probe_agent", side_effect=delayed_agent), \
                 patch("tui.app.installed", return_value=False):
                app = DevboxTUI()
                app.open_menu()
                await asyncio.sleep(0.025)
                app._invalidate_agent_scan()
                self.assertIsNone(app._agent_scan_task)
                self.assertEqual(app._agent_scan_completed_at, 0.0)
                await asyncio.sleep(0.20)
                # An obsolete probe cannot overwrite a just-installed state
                # or mark the cache fresh after invalidation.
                self.assertEqual(app.ponytail_agents["claude"], "Checking")
                self.assertEqual(app._agent_scan_completed_at, 0.0)
                app._schedule_agent_scan()
                await asyncio.wait_for(app._agent_scan_task, timeout=2)
                self.assertEqual(app.ponytail_agents["claude"], "Installed")
        asyncio.run(scenario())

    def test_multiple_installed_agents_without_receipts(self):
        discovered = {
            "claude": "Checking", "codex": "Checking", "copilot": "Checking",
            "opencode": "Unavailable", "gemini": "Unavailable",
        }
        async def scenario():
            with patch("tui.app.discover_agents", return_value=discovered.copy()), \
                 patch("tui.app.probe_agent", side_effect=lambda agent: {
                     "claude": "Installed", "codex": "Installed",
                     "copilot": "Missing",
                 }[agent]), \
                 patch("tui.app.installed", return_value=False):
                app = DevboxTUI()
                app.open_menu()
                await asyncio.wait_for(app._agent_scan_task, timeout=2)
                self.assertEqual(app.available["ponytail"], "Partial")
                self.assertEqual(app.ponytail_agents["copilot"], "Missing")
                self.assertEqual(app.ponytail_agents["codex"], "Installed")
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
