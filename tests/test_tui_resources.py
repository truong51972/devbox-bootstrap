"""Unified resource manager regressions."""
import unittest
from unittest.mock import patch

from tui.app import DevboxTUI
from tui.toolkit.resources import Resource, plan, newer


class ResourceManagerTests(unittest.TestCase):
    def test_direct_entry_and_common_selection(self):
        app = DevboxTUI()
        for menu, scope in (("environment", "development"), ("agents", "ai")):
            with patch("tui.toolkit.resources.local_rows", return_value=(
                Resource("x", "X", "TOOLS", True, "Missing"),
                Resource("y", "Y", "TOOLS", False, "Installed", update="Available", can_update=True),
                Resource("z", "Z", "TOOLS", True, "Installed", update="Unknown"),
            )):
                app.open_menu(menu)
                self.assertEqual(app.screen, "resources")
                self.assertEqual(app.resource_scope, scope)
                app.resource_defaults()
                self.assertEqual(app.resource_list.current_values, ["x"])
                app.resource_updates()
                self.assertEqual(app.resource_list.current_values, ["x", "y"])
                app.back()
                self.assertEqual(app.screen, "home")

    def test_mixed_plan_and_dependencies(self):
        rows = (
            Resource("docker", "Docker", "CONTAINERS", True, "Missing"),
            Resource("nvidia", "NVIDIA", "CONTAINERS", True, "Missing"),
            Resource("uv", "uv", "TOOLS", True, "Installed", update="Available", can_update=True),
            Resource("fzf", "fzf", "TOOLS", True, "Installed", update="Available"),
        )
        ops = plan("development", rows, ["nvidia", "uv", "fzf"])
        self.assertEqual([(o.verb, o.key) for o in ops],
                         [("Install", "docker"), ("Install", "nvidia"), ("Update", "uv"), ("Skip", "fzf")])
        self.assertIn("--upgrade", ops[2].command)

    def test_release_version_comparison(self):
        self.assertEqual(newer("1.9.0", "1.10.0"), "Available")
        self.assertEqual(newer("2.0.0", "1.0.0"), "Current")
        self.assertEqual(newer("1.0.0", ""), "Unknown")

    def test_unknown_can_retry_verified_provider(self):
        row = Resource("uv", "uv", "TOOLS", True, "Installed", update="Unknown", can_update=True)
        self.assertEqual(row.action, "Update")
        self.assertTrue(row.bulk_update)
        self.assertEqual(row.status, "Update unknown")


if __name__ == "__main__":
    unittest.main()
