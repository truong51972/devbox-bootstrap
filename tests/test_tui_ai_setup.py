"""AI setup preset, separation and explicit-consent regressions."""
import io
import unittest
from unittest.mock import patch

from tui.app import DevboxTUI
from tui.toolkit import agent_setup, environment
from tui.toolkit.cli import main


class AgentSetupTests(unittest.TestCase):
    def test_preset_is_codex_only_and_explicit_skills(self):
        keys = agent_setup.DEFAULT
        self.assertIn("codex", keys)
        self.assertTrue({"rtk", "skills-cli", "ponytail"} <= set(keys))
        self.assertEqual(len([k for k in keys if k.startswith("skill:")]), 6)
        self.assertFalse(set(keys) & {"claude", "copilot", "opencode", "gemini", "agy"})
        self.assertNotIn("--all", agent_setup.plan(keys).command)
        self.assertEqual(agent_setup.selection(("skill:context-management",)),
                         ("codex", "skills-cli", "skill:context-management"))
        self.assertEqual(agent_setup.selection(("copilot",)), ("copilot",))
        for keys in ((), ("bad",), ("codex", "codex")):
            with self.assertRaises(ValueError):
                agent_setup.selection(keys)

    def test_cli_preview_and_confirmation(self):
        with patch("tui.toolkit.cli.run") as run, patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(main(["agent", "setup"]), 0)
            self.assertIn("Preview only", out.getvalue())
            run.assert_not_called()
            run.return_value = 0
            self.assertEqual(main(["agent", "setup", "copilot", "--yes"]), 0)
            self.assertEqual(run.call_args.args[0].command[-1], "copilot")

    def test_default_selection_and_cancel(self):
        app = DevboxTUI()
        app.open_toolkit("Coding Agents")
        app.toolkit_list.set_query("setup ai agents")
        app.toolkit_open_action()
        self.assertEqual(app.screen, "toolkit_ai_setup")
        self.assertEqual(set(app.ai_setup_list.current_values), set(agent_setup.DEFAULT))
        app.ai_setup_list.set_query("copilot")
        app.ai_setup_defaults()
        self.assertEqual(set(app.ai_setup_list.current_values), set(agent_setup.DEFAULT))
        app.ai_setup_list.set_query("")
        app.ai_setup_confirm()
        self.assertEqual(app.screen, "toolkit_confirm")
        self.assertEqual(app.toolkit_confirm.current_value, "no")
        self.assertIn("codex", app.toolkit_workflow.command)
        app.toolkit_confirm_action()
        self.assertEqual(app.screen, "toolkit_ai_setup")
        self.assertIsNone(app.toolkit_workflow)
        app.back()
        self.assertEqual(app.screen, "toolkit")

    def test_development_tools_exclude_ai_extensions(self):
        app = DevboxTUI()
        app.open_toolkit("Environment")
        app.toolkit_list.set_query("install tools")
        app.toolkit_open_action()
        self.assertEqual(app.screen, "select")
        self.assertFalse({e.key for e in app.selector.entries} & agent_setup.EXTENSIONS)
        with patch("tui.toolkit.environment.inspect_component_details", return_value={}):
            self.assertFalse({row.key for row in environment.tool_rows()} & agent_setup.EXTENSIONS)

    def test_ai_extension_selection_is_separate(self):
        app = DevboxTUI()
        app.open_toolkit("Coding Agents")
        app.toolkit_list.set_query("install agent extensions")
        app.toolkit_open_action()
        self.assertEqual(app.screen, "select")
        self.assertEqual({e.key for e in app.selector.entries}, agent_setup.EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
