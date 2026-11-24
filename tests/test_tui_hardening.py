import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tui.app import DevboxTUI
from tui.backend import read_run_events
from tui.catalog import ORDER
from tui.execution import run_env, wait_for_run
from tui.reporting import RunReport, read_report, write_report
from tui.tasks import BackgroundTasks
from tui.update_check import check_update


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_component_contract_matches_install_and_upgrade(self):
        install = (ROOT / "setup-ubuntu.sh").read_text()
        upgrade = (ROOT / "utils/upgrade.sh").read_text()
        codes = re.findall(r"^\s*run_component ([a-z0-9-]+) ", install, re.M)
        self.assertEqual([code for code in codes if code != "clean"], list(ORDER))
        order = re.search(r"^    for component in ([a-z0-9 -]+); do$", upgrade, re.M).group(1).split()
        self.assertEqual(order, list(ORDER))

    def test_report_round_trip_and_old_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "test.log"
            log.touch()
            self.assertIsNone(read_report(log))
            report = RunReport("clean", "2026-01-01", 1.2, 0, False,
                               {"apt-cache": "SKIPPED"}, {"apt-cache": "not available"}, "done")
            self.assertEqual(report.heading, "PARTIAL")
            write_report(log, report)
            self.assertEqual(read_report(log), report)
            log.with_suffix(".json").write_text('{"schema":99}')
            self.assertIsNone(read_report(log))

    def test_detail_events_are_incremental(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.events"
            path.write_text('STATUS\tapt-cache\tCLEANED\nDETAIL\tapt-cache\t' + json.dumps("cache\nsize") + "\nSTATUS\t")
            statuses, details, offset = read_run_events(path, 0)
            self.assertEqual(statuses, [("apt-cache", "CLEANED")])
            self.assertEqual(details, [("apt-cache", "cache\nsize")])
            with path.open("a") as stream:
                stream.write("npm-cache\tSKIPPED\n")
            self.assertEqual(read_run_events(path, offset)[0], [("npm-cache", "SKIPPED")])

    def test_confirmation_environment_never_inherits_consent(self):
        with patch.dict(os.environ, {"DEVBOX_CONFIRM_DOCKER_GROUP": "yes"}):
            self.assertEqual(run_env(Path("/tmp/run.events"), set())["DEVBOX_CONFIRM_DOCKER_GROUP"], "no")

    def test_no_subprocess_during_construction_or_redraw(self):
        with patch("subprocess.run", side_effect=AssertionError("blocking subprocess")):
            app = DevboxTUI()
            app.open_menu()
            for _ in range(40):
                app.selector.move(1)
                app._component_details()
            self.assertEqual(app.screen, "select")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_replaced_task_is_reaped_on_close(self):
        tasks = BackgroundTasks()
        finished = asyncio.Event()

        async def worker():
            try:
                await asyncio.sleep(10)
            finally:
                finished.set()

        old = tasks.start("scan", worker())
        await asyncio.sleep(0)
        new = tasks.start("scan", asyncio.sleep(10))
        await tasks.close()
        self.assertTrue(old.cancelled() and new.cancelled())
        self.assertTrue(finished.is_set())

    async def test_log_failure_waits_for_native_child(self):
        proc = await asyncio.create_subprocess_exec("bash", "-c", "sleep 0.1")
        def fail():
            raise OSError("log read failed")
        with self.assertRaises(OSError):
            await wait_for_run(proc, fail, interval=0.01)
        self.assertEqual(proc.returncode, 0)

    async def test_real_git_update_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            upstream, local = base / "upstream", base / "local"
            def git(*args):
                return subprocess.run(["git", *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()
            git("init", "-b", "main", upstream)
            git("-C", upstream, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "initial")
            git("clone", upstream, local)
            git("-C", upstream, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "new")
            with patch("tui.update_check.ORIGINS", {str(upstream)}):
                result = await check_update(local)
            self.assertEqual(result.state, "available")
            self.assertEqual(result.commits, 1)
            self.assertEqual(git("-C", local, "rev-parse", "HEAD"), result.current)
            self.assertEqual(git("-C", local, "rev-parse", "refs/devbox/update-check"), result.latest)
            self.assertNotEqual(result.current, result.latest)
