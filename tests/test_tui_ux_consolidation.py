"""Cross-workspace regression checks for the shared interaction contract."""
import unittest
from unittest.mock import patch

from tui.app import DevboxTUI
from tui.toolkit.resources import Resource
from tui.toolkit import settings
from tui.ui import Entry, KeyboardList
from tui.views import fit_shortcuts


class ConsolidationTests(unittest.TestCase):
    def test_status_filters_and_retry_candidates(self):
        app = DevboxTUI()
        rows = (Resource("one", "One", "TOOLS", True, "Installed", update="Available", can_update=True),
                Resource("two", "Two", "TOOLS", True, "Installed", update="Unknown", can_update=True),
                Resource("three", "Three", "TOOLS", True, "Missing"))
        with patch("tui.toolkit.resources.local_rows", return_value=rows):
            app.resource_open("development")
        app.resource_updates()
        self.assertEqual(app.resource_list.current_values, ["one"])
        app.resource_retry_checks()
        self.assertEqual(app.resource_list.current_values, ["one", "two"])
        app.resource_cycle_filter()
        self.assertEqual([row.key for row in app.resource_list.visible], ["one", "two"])
        app.resource_cycle_filter()
        self.assertEqual([row.key for row in app.resource_list.visible], ["three"])
        self.assertEqual(app.resource_list.current_values, ["one", "two"])
        self.assertEqual(rows[1].status_parts, (("Installed", "Installed"), ("Unknown", "Update unknown")))

    def test_shortcuts_are_generated_from_available_callbacks(self):
        def noop():
            pass
        widget = KeyboardList([Entry("a", "A")], on_enter=noop, on_back=noop, on_help=noop,
                              on_change=noop, on_details=noop)
        hints = widget.shortcut_hints()
        self.assertIn("i Details", hints)
        self.assertNotIn("Space Select", hints)
        self.assertNotIn("r Refresh", hints)
        compact = fit_shortcuts(hints, 32)
        self.assertIn("Enter Open", compact)
        self.assertIn("Esc Back", compact)
        self.assertLessEqual(len(compact), 32)

    def test_catalog_search_and_full_detail_preserve_selection(self):
        app = DevboxTUI()
        app.open_menu("network")
        app.toolkit_list.set_query("port busy")
        self.assertIn("net.port", [entry.key for entry in app.toolkit_list.visible])
        app.toolkit_list.index = next(i for i, entry in enumerate(app.toolkit_list.visible) if entry.key == "net.port")
        app._show_preview(app.toolkit_details)
        self.assertEqual(app.screen, "preview_detail")
        self.assertIn("WHEN TO USE", app.info_view.text)
        app.back()
        self.assertEqual(app.screen, "toolkit")
        self.assertEqual(app.toolkit_list.current_value, "net.port")
        self.assertEqual(app.toolkit_list.query, "port busy")

    def test_preferences_validation_and_overrides(self):
        self.assertEqual(settings.inventory_ttl({"inventory_ttl": 60}), 60)
        self.assertEqual(settings.inventory_ttl({"inventory_ttl": True}), 900)
        with patch.dict("os.environ", {"DEVBOX_CHECK_UPDATES": "0", "DEVBOX_THEME": "mono"}):
            self.assertFalse(settings.startup_updates({"startup_updates": True}))
            self.assertEqual(settings.theme({"theme": "minimal"}), "mono")


if __name__ == "__main__":
    unittest.main()
