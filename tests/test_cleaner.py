import unittest
from unittest.mock import patch
from tui.cleaner import BY_KEY, SAFE_KEYS, Scan, select_keys, docker_prefix, main
from tui.app import DevboxTUI
from tui.backend import build_command
from tui.ui import Entry, KeyboardList


class CleanerTests(unittest.TestCase):
    def test_all_is_safe(self):
        selected = select_keys(None, True, set(BY_KEY))
        self.assertEqual(set(selected), SAFE_KEYS)
        for key in ("docker-volumes", "docker-unused-images", "uv-cache"):
            self.assertNotIn(key, selected)

    def test_selection_validation(self):
        for value in ("unknown", "pip-cache,pip-cache", "pip-cache;rm"):
            with self.assertRaises(ValueError):
                select_keys(value, False, set(BY_KEY))

    def test_backend_risk_guard(self):
        with self.assertRaises(ValueError):
            build_command("clean", ["docker-volumes"])
        self.assertIn("--allow-risky", build_command(
            "clean", ["docker-volumes"], allow_risky=True))
        self.assertNotIn("--yes", build_command("clean", ["docker-volumes"], dry_run=True))

    @patch("tui.cleaner.scan", return_value=[])
    @patch("tui.cleaner.os.geteuid", return_value=1000)
    @patch("tui.cleaner.execute")
    def test_preview_never_executes(self, execute, _uid, _scan):
        self.assertEqual(main(["--only", "docker-volumes"]), 0)
        execute.assert_not_called()
        with self.assertRaises(SystemExit):
            main(["--only", "docker-volumes", "--yes"])
        execute.assert_not_called()

    @patch.dict("os.environ", {"DOCKER_HOST": "tcp://remote:2375", "DOCKER_CONTEXT": ""})
    def test_remote_refused(self):
        with self.assertRaises(RuntimeError):
            docker_prefix()

    def test_tui_all_clears_manual_selection(self):
        app = DevboxTUI()
        widget = app.cleaner_list
        widget.entries = [Entry("pip-cache", "pip"), Entry("docker-volumes", "Volumes")]
        widget.current_values = ["docker-volumes"]
        bindings = widget.window.content.key_bindings.get_bindings_for_keys(("a",))
        self.assertTrue(bindings)
        bindings[-1].handler(None)
        self.assertEqual(widget.current_values, ["pip-cache"])

    def test_cleaner_progress_uses_cleaner_status_keys(self):
        app = DevboxTUI()
        app.status = {"pip-cache": "CLEANED"}
        self.assertIn("1 / 1 complete", "".join(text for _, text in app._progress_tokens()))

    @patch("tui.cleaner.shutil.which", return_value=None)
    @patch("tui.cleaner.os.geteuid", return_value=1000)
    @patch("tui.cleaner.execute", return_value=True)
    @patch("tui.cleaner.scan", return_value=[
        Scan("pip-cache", True, "1 MiB", ""),
        Scan("docker-volumes", True, "1 GiB", ""),
    ])
    def test_cli_all_executes_only_safe_items(self, _scan, execute, _uid, _which):
        self.assertEqual(main(["--all", "--yes"]), 0)
        execute.assert_called_once_with(BY_KEY["pip-cache"], None)

    def test_no_volume_or_tagged_image_in_safe_commands(self):
        for key in SAFE_KEYS:
            command = BY_KEY[key].command
            self.assertNotIn("--volumes", command)
            self.assertNotIn("--all", command)
            self.assertNotIn("autoremove", command)


if __name__ == "__main__":
    unittest.main()
