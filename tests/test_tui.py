"""Tests for pure TUI decisions and bounded event/log readers."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tui.app import ROOT, COMPONENTS, build_command, log_tail, read_events


class TUIBasicTests(unittest.TestCase):
    def test_command_dispatch(self):
        self.assertEqual(
            build_command("install", ["fzf", "direnv"]),
            ["bash", str(ROOT / "setup-ubuntu.sh"), "--only", "fzf,direnv"],
        )
        self.assertEqual(
            build_command("upgrade", ["uv"]),
            ["bash", str(ROOT / "setup-ubuntu.sh"), "--upgrade", "--only", "uv"],
        )
        self.assertEqual(build_command("doctor", []), ["bash", str(ROOT / "setup-ubuntu.sh"), "--doctor"])
        self.assertEqual(build_command("preflight", []), ["bash", str(ROOT / "setup-ubuntu.sh"), "--preflight"])
        self.assertEqual(build_command("upgrade", ["fzf"], dry_run=True), ["bash", str(ROOT / "setup-ubuntu.sh"), "--upgrade", "--dry-run", "--only", "fzf"])
        self.assertEqual(build_command("update", []), ["bash", str(ROOT / "bin" / "devbox"), "--update"])

    def test_invalid_command_and_selection(self):
        for action, selected in [("delete", []), ("install", []), ("upgrade", ["not-a-tool"]), ("install", ["fzf; sudo reboot"])]:
            with self.subTest(action=action, selected=selected):
                with self.assertRaises(ValueError):
                    build_command(action, selected)

    def test_component_ids_are_unique(self):
        keys = [key for key, _label in COMPONENTS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_event_feed_handles_partial_records(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events"
            path.write_bytes(b"STATUS\tfzf\tRUNNING\nSTATUS\tfzf\tUP")
            first, offset = read_events(path, 0)
            self.assertEqual(first, [("fzf", "RUNNING")])
            self.assertEqual(offset, len(b"STATUS\tfzf\tRUNNING\n"))
            with path.open("ab") as output:
                output.write(b"DATED\nSTATUS\tuv\tUPDATED\n")
            second, updated = read_events(path, offset)
            self.assertEqual(second, [("fzf", "UPDATED"), ("uv", "UPDATED")])
            self.assertGreater(updated, offset)

    def test_large_log_is_bounded(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            path.write_text("".join(f"line {x}: {'X' * 100}\n" for x in range(2000)), encoding="utf-8")
            lines = log_tail(path, 9).splitlines()
            self.assertEqual(len(lines), 9)
            self.assertTrue(lines[-1].startswith("line 1999:"))
            self.assertTrue(lines[0].startswith("line 1991:"))

if __name__ == "__main__":
    unittest.main()
