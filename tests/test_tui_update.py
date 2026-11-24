import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from tui.app import DevboxTUI
from tui.update_check import UpdateCheck, check_update


class UpdateDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_available(self):
        answers = [(0, "https://github.com/truong51972/devbox-bootstrap.git"),
                   (0, "main"), (0, ""), (0, "old"), (0, ""),
                   (0, "new"), (0, ""), (0, "3")]
        with patch("tui.update_check.git", side_effect=answers) as git:
            self.assertEqual(await check_update(Path("/repo")),
                             UpdateCheck("available", "old", "new", 3))
        self.assertNotIn("merge", [call.args[1] for call in git.call_args_list])

    async def test_dirty_no_fetch(self):
        with patch("tui.update_check.git", side_effect=[
            (0, "https://github.com/truong51972/devbox-bootstrap.git"),
            (0, "main"), (0, " M file"),
        ]) as git:
            self.assertEqual((await check_update(Path("/repo"))).state, "dirty")
            self.assertEqual(git.await_count, 3)

    async def test_diverged_no_prompt(self):
        with patch("tui.update_check.git", side_effect=[
            (0, "https://github.com/truong51972/devbox-bootstrap.git"),
            (0, "main"), (0, ""), (0, "old"), (0, ""),
            (0, "new"), (1, ""),
        ]):
            self.assertEqual((await check_update(Path("/repo"))).state, "not-fast-forward")

    async def test_offline_and_timeout(self):
        with patch("tui.update_check.git", return_value=(128, "")):
            self.assertEqual((await check_update(Path("/repo"))).state, "unavailable")
        with patch("tui.update_check._check", side_effect=asyncio.TimeoutError):
            self.assertEqual((await check_update(Path("/repo"))).state, "unavailable")


class StartupUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_default_and_yes_dispatch(self):
        app = DevboxTUI()
        with patch("tui.app.check_update", return_value=UpdateCheck("available", "old", "new", 2)):
            await app._check_startup_update()
            self.assertEqual(app.screen, "update_prompt")
            self.assertEqual(app.update_choices.current_value, "no")
            app._answer_update()
            self.assertEqual(app.screen, "home")
            self.assertIsNone(app.pending_update)
            await app._check_startup_update()
            with patch.object(app, "start") as start:
                app._answer_update(True)
                start.assert_called_once_with("update", [])
                self.assertEqual(app.update_revision, "new")

    async def test_defer_prompt_until_home(self):
        app = DevboxTUI()
        app.screen = "select"
        with patch("tui.app.check_update", return_value=UpdateCheck("available", "old", "new", 2)):
            await app._check_startup_update()
        self.assertEqual(app.screen, "select")
        app.navigate("home", app.menu.window)
        self.assertEqual(app.screen, "update_prompt")

    async def test_current_stays_home(self):
        app = DevboxTUI()
        with patch("tui.app.check_update", return_value=UpdateCheck("current")):
            await app._check_startup_update()
        self.assertEqual(app.screen, "home")
        self.assertIsNone(app.pending_update)

    async def test_update_exits_only_on_success(self):
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        import sys

        for code in (0, 1):
            with self.subTest(code=code), TemporaryDirectory() as tmp, \
                    create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
                app = DevboxTUI()
                task = asyncio.create_task(app.app.run_async())
                try:
                    await asyncio.sleep(0.1)
                    with patch("tui.app.STATE_ROOT", Path(tmp)):
                        await app._run("update", [sys.executable, "-c", f"raise SystemExit({code})"], [])
                    if code == 0:
                        await asyncio.wait_for(task, 2)
                        self.assertIn("updated successfully", app.exit_message)
                    else:
                        self.assertEqual(app.screen, "result")
                        self.assertFalse(task.done())
                        self.assertEqual(app.last_code, 1)
                finally:
                    if not task.done():
                        app.app.exit()
                        await asyncio.wait_for(task, 2)


if __name__ == "__main__":
    unittest.main()
