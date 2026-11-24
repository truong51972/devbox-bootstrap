"""RTK local inventory and compact TUI regressions."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tui import rtk_status as rtk
from tui.agent_status import AGENTS, PluginStatus
from tui.app import DevboxTUI


class RtkStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        env = patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "CODEX_HOME": str(self.home / ".codex"),
            "COPILOT_HOME": str(self.home / ".copilot"),
            "GEMINI_CLI_HOME": str(self.home / ".gemini"),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "OPENCODE_CONFIG_DIR": "",
        })
        env.start()
        self.addCleanup(env.stop)

    def write(self, name, text):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def hook(self, file, event, command):
        return self.write(file, json.dumps({"hooks": {event: [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}
        ]}}))

    def test_binary_missing_failed_and_verified(self):
        with patch("tui.rtk_status.executable_path", return_value=None):
            self.assertEqual(rtk.binary_status().state, "Missing")
        with patch("tui.rtk_status.executable_path", return_value="/bin/rtk"), \
             patch("tui.rtk_status.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(rtk.binary_status().state, "Installed")
        with patch("tui.rtk_status.executable_path", return_value="/bin/rtk"), \
             patch("tui.rtk_status.subprocess.run", side_effect=subprocess.TimeoutExpired("rtk", 5)):
            self.assertEqual(rtk.binary_status().state, "Unverified")

    def test_native_hooks_for_each_agent(self):
        for agent, file, event in (
            ("claude", ".claude/settings.json", "PreToolUse"),
            ("codex", ".codex/hooks.json", "PreToolUse"),
            ("copilot", ".copilot/hooks/rtk-rewrite.json", "PreToolUse"),
            ("gemini", ".gemini/settings.json", "BeforeTool"),
        ):
            with self.subTest(agent=agent):
                self.assertEqual(rtk.integration_status(agent, "Checking").state, "Missing")
                self.hook(file, event, f"/usr/local/bin/rtk hook {agent}")
                self.assertEqual(rtk.integration_status(agent, "Checking").state, "Installed")
                self.assertEqual(rtk.integration_status(agent, "Unavailable").state, "Unavailable")

    def test_legacy_codex_rules_are_distinguished_from_hooks(self):
        self.write(".codex/RTK.md", "Use rtk git status")
        self.assertEqual(rtk.integration_status("codex", "Checking").state, "Missing")
        self.write(".codex/AGENTS.md", "# Instructions\n@RTK.md\n")
        result = rtk.integration_status("codex", "Checking")
        self.assertEqual(result.state, "Installed")
        self.assertEqual(result.source, "instructions")
        self.assertIn("no automatic hook", result.reason)

    def test_legacy_wrapper_requires_actual_file(self):
        wrapper = self.home / ".claude/hooks/rtk-rewrite.sh"
        self.hook(".claude/settings.json", "PreToolUse", f"bash {wrapper}")
        self.assertEqual(rtk.integration_status("claude", "Checking").state, "Unverified")
        self.write(".claude/hooks/rtk-rewrite.sh", "#!/bin/sh\nrtk rewrite \"$1\"\n")
        self.assertEqual(rtk.integration_status("claude", "Checking").state, "Installed")

    def test_disabled_invalid_unrelated_and_opencode(self):
        self.write(".claude/settings.json", '{"disableAllHooks":true}')
        self.assertEqual(rtk.integration_status("claude", "Checking").state, "Disabled")
        self.write(".claude/settings.json", "{invalid")
        self.assertEqual(rtk.integration_status("claude", "Checking").state, "Unverified")
        self.hook(".claude/settings.json", "PreToolUse", "other-tool hook claude")
        self.assertEqual(rtk.integration_status("claude", "Checking").state, "Missing")
        self.write(".config/opencode/plugins/rtk.ts", 'export default { "tool.execute.before": () => "rtk" }')
        self.assertEqual(rtk.integration_status("opencode", "Checking").state, "Installed")

    def test_antigravity_plugin_bundle(self):
        with patch("tui.rtk_status.Path.home", return_value=self.home):
            self.assertEqual(rtk.integration_status("agy", "Checking").state, "Missing")
            self.write(".gemini/config/plugins/rtk/plugin.json", '{"name":"rtk"}')
            self.assertEqual(rtk.integration_status("agy", "Checking").state, "Unverified")
            hooks = {"rtk-hook": {"PreToolUse": [{"matcher": "run_command", "hooks": [
                {"type": "command", "command": "rtk hook antigravity"}
            ]}]}}
            path = self.write(".gemini/config/plugins/rtk/hooks.json", json.dumps(hooks))
            self.assertEqual(rtk.integration_status("agy", "Checking").state, "Installed")
            hooks["rtk-hook"]["enabled"] = False
            path.write_text(json.dumps(hooks), encoding="utf-8")
            self.assertEqual(rtk.integration_status("agy", "Checking").state, "Disabled")
            self.assertEqual(rtk.integration_status("agy", "Unavailable").state, "Unavailable")
            self.assertEqual(rtk.integration_status("gemini", "Checking").state, "Missing")

    def test_binary_and_agent_aggregate(self):
        binary = PluginStatus("rtk", "Installed", "binary", "/bin/rtk")
        agents = {"codex": PluginStatus("codex", "Installed", "config", "Hook configured"),
                  "copilot": PluginStatus("copilot", "Unavailable", "PATH", "CLI not installed")}
        self.assertEqual(rtk.RtkInventory(binary, agents).state, "Installed")
        agents["claude"] = PluginStatus("claude", "Missing", "config", "Hook not configured")
        self.assertEqual(rtk.RtkInventory(binary, agents).state, "Partial")

    def test_tui_preserves_rtk_cache_and_condenses_details(self):
        async def scenario():
            discovery = {agent: "Checking" if agent in ("codex", "copilot") else "Unavailable"
                         for agent in AGENTS}
            binary = PluginStatus("rtk", "Installed", "binary", "/bin/rtk")
            local = rtk.RtkInventory(binary, {
                "codex": PluginStatus("codex", "Installed", "local config", "Hook configured"),
                "copilot": PluginStatus("copilot", "Missing", "local config", "Hook not configured"),
            })
            def ponytail(agent):
                return PluginStatus(agent, "Unavailable" if agent == "copilot" else "Installed",
                                    "test", "fixture")
            with patch("tui.app.discover_agents", side_effect=lambda: discovery.copy()), \
                 patch("tui.app.probe_agent", side_effect=ponytail), \
                 patch("tui.app.inspect_rtk", return_value=local) as inspect, \
                 patch("tui.app.inspect_components", return_value={}):
                app = DevboxTUI()
                app.columns = lambda: 120
                app.open_menu("install")
                await asyncio.wait_for(app._agent_scan_task, timeout=2)
                self.assertEqual(app.available["rtk"], "Installed")
                self.assertEqual(app.rtk_inventory.agents["copilot"].state, "Unavailable")
                app.open_menu("install")
                self.assertEqual(app.available["rtk"], "Installed")
                self.assertEqual(inspect.call_count, 1)
                app.selector.set_query("rtk")
                preview = "".join(t for _, t in app._component_details())
                full = "".join(t for _, t in app._component_details(full=True))
                self.assertIn("Binary: Installed", preview)
                self.assertIn("AGENT INTEGRATIONS", preview)
                self.assertNotIn("Hook configured", preview)
                self.assertIn("Hook configured", full)
                self.assertNotIn("INVENTORY", preview)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
