"""Regression tests for Devbox navigation, execution, and safe backend events."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tui.app import ROOT, COMPONENTS, DevboxTUI, build_command, log_tail, read_events
from tui.backend import log_preview
from tui.catalog import ORDER, with_dependencies


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
        self.assertEqual(
            build_command("upgrade", ["fzf"], dry_run=True),
            ["bash", str(ROOT / "setup-ubuntu.sh"), "--upgrade", "--dry-run", "--only", "fzf"],
        )
        self.assertEqual(build_command("update", []), ["bash", str(ROOT / "bin/devbox"), "--update"])

    def test_application_constructs_and_preview_toggle(self):
        app = DevboxTUI()
        self.assertEqual(app.screen, "home")
        self.assertFalse(app.app.mouse_support())
        self.assertFalse(app.dry_run)
        self.assertFalse(app.busy)
        app.toggle_dry_run()
        self.assertTrue(app.dry_run)
        self.assertIn("DRY RUN", app._selection_summary())
        app.toggle_dry_run()
        self.assertFalse(app.dry_run)

    def test_menu_component_confirmation_and_dependencies(self):
        app = DevboxTUI()
        self.assertEqual(app.menu.current_value, "install")
        app.open_menu()
        self.assertEqual(app.screen, "select")
        app.available["docker"] = "Missing"
        app.selector.current_values = ["nvidia"]
        app.confirm_selection()
        self.assertEqual(app.screen, "confirm")
        self.assertEqual(app.selected, ["docker", "nvidia"])
        self.assertEqual(app.auto_added, ["docker"])
        self.assertIn("docker_group", [option for option, _ in app.options.values])
        self.assertFalse(app.options.current_values)
        app.back()
        self.assertEqual(app.screen, "select")
        app.back()
        self.assertEqual(app.screen, "home")

    def test_help_and_log_navigation_are_independent(self):
        with TemporaryDirectory() as tmp:
            with patch("tui.app.STATE_ROOT", Path(tmp)):
                folder = Path(tmp) / "logs"
                folder.mkdir()
                path = folder / "20260101-doctor-test.log"
                path.write_text("line 1\nline 2\n", encoding="utf-8")
                app = DevboxTUI()
                app.list_history()
                self.assertEqual(app.screen, "logs")
                app.open_history()
                self.assertEqual(app.screen, "view_log")
                app.help_return_screen = app.screen
                app.navigate("help", app.help_view)
                app.back()
                self.assertEqual(app.screen, "view_log")
                app.back()
                self.assertEqual(app.screen, "logs")
                app.back()
                self.assertEqual(app.screen, "home")

    def test_start_reserves_execution_before_async_scheduling(self):
        app = DevboxTUI()
        with patch("tui.app.asyncio.create_task") as task:
            app.start("doctor")
            self.assertTrue(app.busy)
            self.assertEqual(app.screen, "run")
            task.assert_called_once()
            # Close a coroutine that the mocked scheduler never schedules.
            task.call_args.args[0].close()
            app.start("preflight")
            task.assert_called_once()
            self.assertIn("already active", app.message)

    def test_keyboard_only_navigation_in_live_terminal_session(self):
        """Exercise the actual key bindings, not just screen methods."""
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        async def scenario():
            with create_pipe_input() as input_pipe:
                with create_app_session(input=input_pipe, output=DummyOutput()):
                    app = DevboxTUI()
                    run = asyncio.create_task(app.app.run_async())
                    try:
                        await asyncio.sleep(0.10)
                        input_pipe.send_text("\r")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.screen, "select")
                        input_pipe.send_text(" ")  # Toggle current checkbox.
                        await asyncio.sleep(0.10)
                        self.assertTrue(app.selector.current_values)
                        input_pipe.send_text("\r")
                        await asyncio.sleep(0.10)
                        self.assertEqual(app.screen, "confirm")
                        input_pipe.send_text("d")
                        await asyncio.sleep(0.10)
                        self.assertTrue(app.dry_run)
                        input_pipe.send_text("\x1b")
                        await asyncio.sleep(0.15)
                        self.assertEqual(app.screen, "select")
                        input_pipe.send_text("\x1b")
                        await asyncio.sleep(0.15)
                        self.assertEqual(app.screen, "home")
                        input_pipe.send_text("q")
                        await asyncio.wait_for(run, 2)
                    finally:
                        if not run.done():
                            app.app.exit()
                            await asyncio.wait_for(run, 2)

        asyncio.run(scenario())

    def test_invalid_command_and_selection(self):
        for action, selected in [
            ("delete", []), ("install", []), ("upgrade", ["not-a-tool"]),
            ("install", ["fzf; sudo reboot"]),
        ]:
            with self.subTest(action=action, selected=selected):
                with self.assertRaises(ValueError):
                    build_command(action, selected)

    def test_dependency_resolver(self):
        present = {code: "Missing" for code in ORDER}
        resolved, added = with_dependencies(["nvidia", "powerlevel10k"], present)
        self.assertEqual(resolved, ["zsh", "powerlevel10k", "docker", "nvidia"])
        self.assertEqual(added, ["zsh", "docker"])
        present["docker"] = "Installed"
        self.assertEqual(with_dependencies(["nvidia"], present), (["nvidia"], []))

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
            self.assertIn("line 1999", log_preview(path, max_bytes=400))

    def test_execution_failure_is_visible_and_releases_slot(self):
        with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)):
            app = DevboxTUI()
            app.busy = True
            app.current_action = "Install"
            app.status["fzf"] = "QUEUED"

            async def task():
                await app._run(
                    "doctor",
                    ["bash", "-c", 'printf "STATUS\\tfzf\\tRUNNING\\n" >> "$DEVBOX_EVENT_FILE"; echo job-output; exit 7'],
                    ["fzf"],
                )

            asyncio.run(task())
            self.assertFalse(app.busy)
            self.assertEqual(app.last_code, 7)
            self.assertEqual(app.screen, "result")
            self.assertEqual(app.status["fzf"], "FAILED")
            self.assertIn("job-output", app.results_view.text)
            self.assertTrue(app.log_path.is_file())

    def test_execution_success_saves_log(self):
        with TemporaryDirectory() as tmp, patch("tui.app.STATE_ROOT", Path(tmp)):
            app = DevboxTUI()
            app.busy = True
            app.current_action = "Preflight"
            asyncio.run(app._run("preflight", ["bash", "-c", "echo host-ready"], []))
            self.assertEqual(app.last_code, 0)
            self.assertIn("host-ready", app.results_view.text)
            self.assertFalse(app.busy)


if __name__ == "__main__":
    unittest.main()
