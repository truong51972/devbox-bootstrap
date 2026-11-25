"""Resource plans must use the common fullscreen execution pipeline."""
import asyncio
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from tui.app import DevboxTUI
from tui.backend import read_run_events
from tui.reporting import read_report
from tui.toolkit.resources import Operation
from tui.toolkit.resource_batch import batch_command, consent_entries, needs_sudo


class ResourceBatchTests(unittest.TestCase):
    def test_consent_and_sudo(self):
        ops = (Operation("Install", "docker", "Docker", ("true",)),
               Operation("Update", "zsh", "Zsh", ("true",)),
               Operation("Install", "keychain", "Keychain", ("true",)))
        self.assertEqual([e.key for e in consent_entries(ops)], ["docker_group", "ssh_key"])
        self.assertTrue(needs_sudo(ops, "development"))
        self.assertFalse(needs_sudo(ops, "ai"))

    def test_real_batch_events_and_failure(self):
        ops = (Operation("Update", "uv", "uv", ("bash", "-c",
                    'printf "STATUS\\tuv\\tUPDATED\\nSTATUS\\tgh\\tUPDATED\\n" >> "$DEVBOX_EVENT_FILE"')),
               Operation("Update", "gh", "GH", ("bash", "-c", "exit 7")),
               Operation("Install", "fzf", "fzf", ("true",)))
        with TemporaryDirectory() as tmp:
            event = Path(tmp) / "events"
            result = subprocess.run(batch_command(ops), env=dict(os.environ, HOME=tmp, DEVBOX_EVENT_FILE=str(event)),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 7, result.stderr)
            states, _, _ = read_run_events(event, 0)
            self.assertEqual(states, [("uv", "RUNNING"), ("uv", "UPDATED"), ("gh", "RUNNING"), ("gh", "FAILED")])

    def test_run_in_fullscreen_and_persist_report(self):
        async def scenario():
            app = DevboxTUI()
            app.resource_scope = "ai"
            app.resource_operations = (Operation("Update", "codex", "Codex", ("bash", "-c", "echo updated-cli")),)
            app.resource_prepare_confirmation()
            app.resource_confirm.index = 2
            with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)), \
                 patch.dict(os.environ, {"HOME": tmp}), patch.object(app, "_authorize_sudo", new_callable=AsyncMock) as sudo:
                app.resource_confirm_action()
                self.assertEqual(app.screen, "run")
                self.assertTrue(app.busy)
                app.back()
                self.assertEqual(app.screen, "run")
                await app.run_task
                sudo.assert_not_awaited()
                self.assertEqual(app.screen, "result")
                self.assertIn("updated-cli", app.results_view.text)
                self.assertEqual(app.status["codex"], "COMPLETED")
                self.assertEqual(read_report(app.log_path).status, {"codex": "COMPLETED"})
                with patch.object(app, "resource_refresh") as refresh:
                    app.back()
                    self.assertEqual(app.screen, "resources")
                    refresh.assert_called_once_with(force=True)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
