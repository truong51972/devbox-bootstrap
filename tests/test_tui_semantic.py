"""Semantic color regression tests across scrollable and list views."""
from __future__ import annotations

import unittest
from prompt_toolkit.document import Document

from tui.app import DevboxTUI
from tui.reporting import RunReport
from tui.semantic import FragmentLexer, SemanticLexer, log_fragments, plan_fragments, report_fragments
from tui.ui import focused_status_style, status_style, STATUS_STYLES


class SemanticColorTests(unittest.TestCase):
    def test_report_statuses_and_counts_preserve_text(self):
        cases = [
            ("  PARTIAL — Upgrade: Completed successfully.", "class:warning", "PARTIAL"),
            ("  SUCCESS — Install: Completed successfully.", "class:installed", "SUCCESS"),
            ("  FAILED — Upgrade: Failed.", "class:error", "FAILED"),
            ("  ✓  Docker Engine              UPDATED", "class:installed", "UPDATED"),
            ("  ✓  uv (Python)                  UP_TO_DATE", "class:installed", "UP_TO_DATE"),
            ("  ·  RTK                          SKIPPED", "class:warning", "SKIPPED"),
            ("  !  Docker Engine                FAILED", "class:error", "FAILED"),
            ("  >  Docker Engine                RUNNING", "class:running", "RUNNING"),
            ("  Duration: 13.2s | 3 updated | 4 skipped", "class:warning", "4 skipped"),
        ]
        for line, style, token in cases:
            with self.subTest(line=line):
                fragments = report_fragments(line)
                self.assertIn((style, token), fragments)
                self.assertEqual("".join(text for _, text in fragments), line)

    def test_result_log_boundary_and_explicit_log_levels(self):
        raw = "  ✓  unexpected raw output           UPDATED"
        doc = Document("  LAST OUTPUT\n" + raw + "\n[devbox] WARNING: skipped\nERROR: failed")
        lexer = SemanticLexer("result").lex_document(doc)
        self.assertEqual(lexer(1), [("class:body", raw)])
        self.assertEqual(lexer(2)[0][0], "class:warning")
        self.assertEqual(lexer(3)[0][0], "class:error")
        self.assertEqual(log_fragments("0 errors")[0][0], "class:body")
        self.assertEqual(log_fragments("[devbox] [OK] verified")[0][0], "class:installed")

    def test_cleaner_and_focus_use_shared_palette(self):
        self.assertEqual(status_style("SAFE | 1 MiB"), "class:installed")
        self.assertEqual(status_style("MANUAL | 1 MiB"), "class:warning")
        self.assertEqual(status_style("SAFE | Checking..."), "class:running")
        self.assertEqual(status_style("MANUAL | Unavailable"), "class:muted")
        self.assertEqual(focused_status_style("UPDATED", True), "class:focus class:installed")
        self.assertEqual(focused_status_style("SKIPPED", True), "class:focus class:warning")
        self.assertIn(("class:warning", "MANUAL"), plan_fragments("  MANUAL  Docker volumes"))
        self.assertEqual(plan_fragments("Warning: restart Docker")[0][0], "class:warning")

    def test_fragment_lexer_preserves_multiline_styles(self):
        lexer = FragmentLexer()
        text = lexer.set_fragments([("class:title", "Test\n"), ("class:body", "State: "),
                                    ("class:missing", "Missing\n")])
        lines = lexer.lex_document(Document(text))
        self.assertIn(("class:missing", "Missing"), lines(1))
        self.assertEqual("".join(t for _, t in lines(1)), "State: Missing")
        old = lexer.invalidation_hash()
        lexer.set_fragments([("class:warning", text)])
        self.assertNotEqual(old, lexer.invalidation_hash())
        self.assertEqual(lexer.lex_document(Document(text))(1)[0][0], "class:warning")

    def test_result_widget_retains_semantic_lexer(self):
        app = DevboxTUI()
        app.current_action = "upgrade"
        app.last_code = 0
        app.last_result = "Completed successfully."
        app.status["docker"] = "UPDATED"
        app.status["rtk"] = "SKIPPED"
        app.run_report = RunReport("upgrade", "", 13.2, 0, False,
                                   {"docker": "UPDATED", "rtk": "SKIPPED"}, {}, app.last_result)
        app._render_result()
        doc = app.results_view.buffer.document
        lexer = app.results_view.control.lexer.lex_document(doc)
        fragments = [fragment for index in range(len(doc.lines)) for fragment in lexer(index)]
        self.assertIn((STATUS_STYLES["PARTIAL"], "PARTIAL"), fragments)
        self.assertIn((STATUS_STYLES["UPDATED"], "UPDATED"), fragments)
        self.assertIn((STATUS_STYLES["SKIPPED"], "SKIPPED"), fragments)
        self.assertIn("LAST OUTPUT", app.results_view.text)


if __name__ == "__main__":
    unittest.main()
