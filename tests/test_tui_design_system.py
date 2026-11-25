"""Regression tests for the shared design foundation."""
import unittest

from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.styles import Style

from tui.ui import Entry, KeyboardList, THEMES, cell_truncate, status_style
from tui.views import fit_shortcuts, shortcut_fragments


class DesignSystemTests(unittest.TestCase):
    def test_cell_truncate_uses_terminal_width(self):
        self.assertEqual(cell_truncate("工具箱", 5), "工具…")
        self.assertEqual(cell_truncate("e\u0301", 1), "e\u0301")
        self.assertEqual(cell_truncate("abc", 0), "")
        self.assertEqual(cell_truncate("abc", 1), "…")

    def test_status_column_fits_wide_labels(self):
        noop = lambda: None
        widget = KeyboardList([Entry("a", "工具箱" * 20, status="Installed"),
                               Entry("b", "Normal", status="Installed")],
                              on_enter=noop, on_back=noop, on_help=noop,
                              on_change=noop, get_columns=lambda: 48)
        lines = "".join(value for _, value in widget.render()).splitlines()
        self.assertTrue(all(get_cwidth(line) <= 46 for line in lines))
        self.assertTrue(all(line.endswith("Installed") for line in lines))
        self.assertEqual(get_cwidth(lines[0]), get_cwidth(lines[1]))

    def test_long_status_does_not_overflow_list(self):
        noop = lambda: None
        widget = KeyboardList([Entry("a", "Recognizable resource", status_parts=(
                                  ("Installed", "Installed"), ("Update unknown with extra evidence", "Update unknown")))],
                              on_enter=noop, on_back=noop, on_help=noop,
                              on_change=noop, get_columns=lambda: 43)
        line = "".join(value for _, value in widget.render()).strip()
        self.assertIn("Recognizable resource", line)
        self.assertLessEqual(get_cwidth(line), 41)

    def test_key_and_action_have_distinct_fragments(self):
        hints = fit_shortcuts("Enter Review  Esc Back  ? Help", 32)
        fragments = shortcut_fragments(hints)
        self.assertIn(("class:key", "Enter"), fragments)
        self.assertEqual("".join(value for _, value in fragments), hints)
        self.assertTrue(Style.from_dict(THEMES["mono"]).get_attrs_for_style_str("class:key").bold)

    def test_update_attention_states(self):
        for state in ("Manual update", "Update unknown", "Update blocked"):
            self.assertEqual(status_style(state), "class:warning")
        self.assertEqual(status_style("Not applicable"), "class:muted")


if __name__ == "__main__":
    unittest.main()
