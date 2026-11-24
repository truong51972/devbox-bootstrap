import unittest
import asyncio
from unittest.mock import patch
from tui.cleaner import BY_KEY, SAFE_KEYS, PROBE_GROUPS, Scan, select_keys, docker_prefix, main
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

    def test_pending_and_unavailable_rows_cannot_be_selected(self):
        app = DevboxTUI()
        app.cleaner_rows = {"pip-cache": Scan("pip-cache", True, "1 MiB", ""),
                            "npm-cache": Scan("npm-cache", False, "-", "missing")}
        app._cleaner_entries()
        widget = app.cleaner_list
        widget.index = next(i for i, e in enumerate(widget.entries) if e.key == "docker-volumes")
        widget.toggle()
        self.assertEqual(widget.current_values, [])
        widget.window.content.key_bindings.get_bindings_for_keys(("a",))[-1].handler(None)
        self.assertEqual(widget.current_values, ["pip-cache"])

    @patch("tui.cleaner.scan")
    @patch("tui.cleaner.os.geteuid", return_value=1000)
    def test_explicit_preview_does_not_rescan(self, _uid, scan):
        self.assertEqual(main(["--only", "pip-cache", "--dry-run"]), 0)
        scan.assert_not_called()

    def test_cleaner_confirmation_matches_install_and_upgrade(self):
        app = DevboxTUI()
        app.action = "clean"
        app.cleaner_rows = {"pip-cache": Scan("pip-cache", True, "1 MiB", "")}
        app._cleaner_entries()
        app.cleaner_list.current_values = ["pip-cache"]
        app.confirm_cleaners()
        self.assertFalse(app.dry_run)
        self.assertIn("Enter Clean", app._confirm_shortcuts())
        self.assertIn("1 MiB", app.confirm_plan.text)
        self.assertFalse(app.options.entries)
        self.assertIs(app._confirm_focus(), app.confirm_plan)
        self.assertEqual(len(app._confirm_layout().children), 3)
        app.toggle_dry_run()
        self.assertIn("Enter Preview", app._confirm_shortcuts())
        with patch.object(app, "start") as start:
            app.execute_selection()
            start.assert_called_once_with("clean", ["pip-cache"])

    def test_manual_consent_is_still_required(self):
        app = DevboxTUI()
        app.action = "clean"
        app.cleaner_rows = {"docker-volumes": Scan("docker-volumes", True, "1 GiB", "")}
        app._cleaner_entries()
        app.cleaner_list.current_values = ["docker-volumes"]
        app.confirm_cleaners()
        self.assertFalse(app.dry_run)
        self.assertFalse(app.options.current_values)
        app.execute_selection()
        self.assertFalse(app.busy)
        self.assertIn("acknowledge", app.message.lower())

    def test_no_volume_or_tagged_image_in_safe_commands(self):
        for key in SAFE_KEYS:
            command = BY_KEY[key].command
            self.assertNotIn("--volumes", command)
            self.assertNotIn("--all", command)
            self.assertNotIn("autoremove", command)


class ProgressiveScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_docker_does_not_block_fast_rows_or_back(self):
        app = DevboxTUI()
        release = asyncio.Event()
        fast = asyncio.Event()

        async def probe(group):
            if group == "docker":
                await release.wait()
            if group == "pip-cache":
                fast.set()
            return [Scan(key, True, "1 MiB", "") for key in PROBE_GROUPS[group]]

        with patch("tui.app.probe_group", side_effect=probe):
            app.open_cleaner()
            self.assertEqual(len(app.cleaner_list.entries), len(BY_KEY))
            self.assertFalse(app.busy)
            await asyncio.wait_for(fast.wait(), timeout=1)
            await asyncio.sleep(0)
            self.assertIn("pip-cache", app.cleaner_rows)
            self.assertNotIn("docker-volumes", app.cleaner_rows)
            app.cleaner_list.current_values = ["pip-cache"]
            app.confirm_cleaners()
            self.assertEqual(app.screen, "confirm")
            app.back()
            self.assertEqual(app.screen, "cleaner")
            task = app.cleaner_scan_task
            app.back()
            self.assertEqual(app.screen, "home")
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertNotIn("docker-volumes", app.cleaner_rows)

    async def test_group_failure_isolated(self):
        app = DevboxTUI()

        async def probe(group):
            if group == "docker":
                raise asyncio.TimeoutError()
            return [Scan(key, True, "1 MiB", "") for key in PROBE_GROUPS[group]]

        with patch("tui.app.probe_group", side_effect=probe):
            app.open_cleaner()
            await app.cleaner_scan_task
            self.assertEqual(len(app.cleaner_rows), len(BY_KEY))
            self.assertFalse(app.cleaner_rows["docker-volumes"].available)
            self.assertTrue(app.cleaner_rows["pip-cache"].available)
            self.assertIn("timed out", app.cleaner_rows["docker-volumes"].note)


if __name__ == "__main__":
    unittest.main()
