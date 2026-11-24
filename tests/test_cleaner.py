import unittest
import asyncio
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
from tui.cleaner import (BY_KEY, SAFE_KEYS, PROBE_GROUPS, Scan, Outcome, select_keys, docker_prefix,
                         main, scan_group, size, pip_cache_command, native_outcome, validate_resources,
                         execute, volume_token, eligible_volume)
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
            "clean", ["docker-volumes"], allow_risky=True,
            resources=["volume:example:" + "a" * 64]))
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
    @patch("tui.cleaner.execute", return_value=Outcome("COMPLETED", "unknown"))
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

    def test_uppercase_all_is_global_and_manual_never_selected(self):
        app = DevboxTUI()
        app.cleaner_rows = {key: Scan(key, True, "1 MiB", "") for key in BY_KEY}
        app._cleaner_entries()
        widget = app.cleaner_list
        widget.set_query("npm")
        widget.current_values = ["docker-volumes"]
        widget.window.content.key_bindings.get_bindings_for_keys(("A",))[-1].handler(None)
        self.assertEqual(set(widget.current_values), SAFE_KEYS)
        widget.window.content.key_bindings.get_bindings_for_keys(("N",))[-1].handler(None)
        self.assertFalse(app.cleaner_all_requested)
        self.assertEqual(widget.current_values, [])

    @patch("tui.cleaner.run", side_effect=subprocess.TimeoutExpired("du", 12))
    def test_measurement_timeout_does_not_disable_cache(self, _run):
        with TemporaryDirectory() as tmp:
            self.assertEqual(size(tmp), "unknown")
            with patch("tui.cleaner.shutil.which", return_value="/bin/npm"), \
                    patch("tui.cleaner.checked", return_value=tmp):
                row = scan_group("npm-cache")[0]
            self.assertTrue(row.available)
            self.assertEqual(row.estimate, "unknown")

    @patch("tui.cleaner.docker_df", side_effect=subprocess.TimeoutExpired("docker", 12))
    @patch("tui.cleaner.checked", return_value="daemon-id")
    @patch("tui.cleaner.docker_prefix", return_value=["docker", "--host", "unix:///docker.sock"])
    @patch("tui.cleaner.shutil.which", return_value="/bin/docker")
    def test_docker_size_timeout_falls_back_to_daemon_check(self, *_):
        with patch("tui.cleaner.docker_resources", return_value=()):
            self.assertTrue(all(row.available and row.estimate == "unknown" for row in scan_group("docker")))

    @patch("tui.cleaner.shutil.which", return_value="/bin/pip")
    @patch("tui.cleaner.checked", side_effect=[RuntimeError("no system pip"), "/home/user/.cache/pip"])
    def test_pip_falls_back_to_working_cli(self, *_):
        self.assertEqual(pip_cache_command(), (["pip3"], "/home/user/.cache/pip"))

    def test_native_zero_is_not_cleaned(self):
        result = subprocess.CompletedProcess([], 0, "Total reclaimed space: 0B", "")
        self.assertEqual(native_outcome(result).state, "NO_RECLAIM")
        self.assertEqual(native_outcome(subprocess.CompletedProcess([], 0, "", "")).state, "COMPLETED")

    def test_manual_resources_cannot_bulk_delete(self):
        with self.assertRaises(ValueError):
            build_command("clean", ["docker-volumes"], allow_risky=True)
        with self.assertRaises(ValueError):
            validate_resources(["docker-build-cache"], ["volume:example:" + "a" * 64])

    def test_image_rm_only_exact_id_without_force_or_parent_prune(self):
        prefix = ["docker", "--host", "unix:///docker.sock"]
        token = "image:sha256:" + "a" * 64
        with patch("tui.cleaner.docker_resources", return_value=({"token": token},)), \
                patch("tui.cleaner.run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            outcome = execute(BY_KEY["docker-unused-images"], prefix, [token])
        self.assertEqual(outcome.state, "CLEANED")
        run.assert_called_once_with(prefix + ["image", "rm", "--no-prune", token.removeprefix("image:")], timeout=900)

    def test_recreated_volume_is_not_removed(self):
        prefix = ["docker", "--host", "unix:///docker.sock"]
        old = {"Name": "example", "Driver": "local", "CreatedAt": "2025-01-01"}
        token = volume_token(prefix, old)
        changed = dict(old, CreatedAt="2026-01-01")
        with patch("tui.cleaner.docker_resources", return_value=({"token": token},)), \
                patch("tui.cleaner.checked", return_value=__import__("json").dumps([changed])), \
                patch("tui.cleaner.run") as run:
            outcome = execute(BY_KEY["docker-volumes"], prefix, [token])
        self.assertEqual(outcome.state, "SKIPPED")
        run.assert_not_called()
        self.assertFalse(eligible_volume(dict(old, Labels={"devbox.protect": "true"})))

    def test_no_volume_or_tagged_image_in_safe_commands(self):
        for key in SAFE_KEYS:
            command = BY_KEY[key].command
            self.assertNotIn("--volumes", command)
            if key != "docker-build-cache":
                self.assertNotIn("--all", command)
            self.assertNotIn("autoremove", command)


class ProgressiveScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_includes_late_safe_results_before_confirmation(self):
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
            await asyncio.wait_for(fast.wait(), 1)
            app._select_all_cleaners()
            app.confirm_cleaners()
            self.assertEqual(app.screen, "cleaner")
            self.assertIn("waiting", app.message.lower())
            release.set()
            await app.cleaner_scan_task
            self.assertEqual(set(app.cleaner_list.current_values), SAFE_KEYS)
            app.confirm_cleaners()
            self.assertEqual(app.screen, "confirm")
            self.assertEqual(set(app.selected), SAFE_KEYS)
            command = build_command("clean", app.selected)
            self.assertEqual(set(command[command.index("--only") + 1].split(",")), SAFE_KEYS)

    async def test_manual_deselect_cancels_auto_selection(self):
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
            await asyncio.wait_for(fast.wait(), 1)
            app._select_all_cleaners()
            widget = app.cleaner_list
            widget.index = next(i for i, entry in enumerate(widget.entries) if entry.key == "pip-cache")
            widget.toggle()
            self.assertFalse(app.cleaner_all_requested)
            release.set()
            await app.cleaner_scan_task
            self.assertNotIn("pip-cache", widget.current_values)
            self.assertNotIn("docker-build-cache", widget.current_values)

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
            self.assertNotIn("docker-build-cache", app.cleaner_rows)
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
            self.assertNotIn("docker-build-cache", app.cleaner_rows)

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
            self.assertFalse(app.cleaner_rows["docker-build-cache"].available)
            self.assertTrue(app.cleaner_rows["pip-cache"].available)
            self.assertIn("timed out", app.cleaner_rows["docker-build-cache"].note)


if __name__ == "__main__":
    unittest.main()
