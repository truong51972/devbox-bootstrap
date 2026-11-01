"""Keyboard-first, menu-driven TUI for the Devbox Bash backend.

The UI never installs packages directly. Every operation runs in a subprocess;
verbose logs stay on disk while the UI consumes only bounded tails and events.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from prompt_toolkit import Application
from prompt_toolkit.application import in_terminal
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit
from prompt_toolkit.layout.containers import DynamicContainer
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import CheckboxList, Frame, Label, RadioList, TextArea

from tui.backend import (
    ROOT, STATE_ROOT, FINAL_STATES, build_command, log_tail, log_preview,
    read_events,
)
from tui.catalog import COMPONENTS, GROUPS, ORDER, inventory, with_dependencies

FINISHED_STATES = FINAL_STATES  # Preserve external integrations.
MENU = (
    ("install", "Install components"),
    ("upgrade", "Upgrade components"),
    ("doctor", "Doctor - check configuration"),
    ("preflight", "Preflight - inspect host"),
    ("update", "Update Devbox source"),
    ("logs", "Logs and history"),
    ("exit", "Exit"),
)
HELP = """MAIN MENU          Up/Down (or j/k), Enter to open, Q to quit
COMPONENTS         Up/Down, Space toggle, A select all, N clear
CONFIRMATION       Space toggle optional choices, D toggle dry-run
EXECUTION          Watch live status and recent output; jobs cannot detach
RESULTS            L view log, Enter return to main menu
LOG VIEW           Up/Down and PageUp/PageDown scroll, O open external pager
EVERY SCREEN       Esc go back (unless a job is running), Ctrl-Q quit
                   ? keyboard help

All actions write complete logs to ~/.local/state/devbox-bootstrap/logs.
Dangerous choices are opt-in and disabled by default.
"""


class DevboxTUI:
    def __init__(self) -> None:
        self.screen = "home"
        self.previous_screen = "home"
        self.help_return_screen = "home"
        self.action = ""
        self.current_action = ""
        self.selected: list[str] = []
        self.auto_added: list[str] = []
        self.available = inventory()
        self.status: dict[str, str] = {code: "--" for code in ORDER}
        self.busy = False
        self.dry_run = False
        self.message = "Use arrow keys and Enter to select an action."
        self.process: asyncio.subprocess.Process | None = None
        self.log_path: Path | None = None
        self.event_path: Path | None = None
        self.event_offset = 0
        self.last_code: int | None = None
        self.last_result = ""
        self.run_task: asyncio.Task[None] | None = None

        self.menu = RadioList(list(MENU))
        self.selector = self._make_selector()
        self.options = CheckboxList([("placeholder", "No additional options")])
        self.log_files = RadioList([("", "No history yet")])
        self.status_view = TextArea(text="", read_only=True, focusable=True,
                                    scrollbar=True, wrap_lines=False)
        self.log_view = TextArea(text="", read_only=True, focusable=False,
                                 scrollbar=True, wrap_lines=False)
        self.results_view = TextArea(text="", read_only=True, focusable=True,
                                     scrollbar=True, wrap_lines=False)
        self.history_view = TextArea(text="", read_only=True, focusable=True,
                                     scrollbar=True, wrap_lines=False)
        self.help_view = TextArea(text=HELP, read_only=True, focusable=True,
                                  scrollbar=True, wrap_lines=False)

        self.views = {
            "home": self._page(
                "MAIN MENU", Frame(self.menu, title="Choose an action"),
                "Up/Down: navigate   Enter: open   Q: quit   ?: help"),
            "select": self._page(
                "COMPONENTS", Frame(self.selector, title="Select tools (Space)"),
                "Space: toggle   A: all   N: none   Enter: next   Esc: back"),
            "confirm": self._page(
                "CONFIRM", VSplit([
                    Frame(Label(lambda: self._selection_summary()), title="Plan",
                          width=Dimension(weight=2)),
                    Frame(self.options, title="Optional changes (default OFF)",
                          width=Dimension(weight=3)),
                ], padding=1),
                "Space: optional choice   D: dry-run   Enter: run   Esc: back"),
            "run": self._page(
                "EXECUTION", VSplit([
                    Frame(self.status_view, title="Component status",
                          width=Dimension(weight=2)),
                    Frame(self.log_view, title="Recent output",
                          width=Dimension(weight=3)),
                ], padding=1),
                "Running in foreground-managed subprocess; full output saved to disk"),
            "result": self._page(
                "RESULT", Frame(self.results_view, title="Execution summary"),
                "L: view log   Enter: main menu   Esc: main menu"),
            "logs": self._page(
                "LOG HISTORY", Frame(self.log_files, title="Recent runs (newest first)"),
                "Enter: open log   Esc: main menu"),
            "view_log": self._page(
                "LOG VIEWER", Frame(self.history_view, title="Log tail (max 1 MiB)"),
                "Up/Down/PgUp/PgDn: scroll   O: external pager   Esc: back"),
            "help": self._page(
                "KEYBOARD HELP", Frame(self.help_view, title="Keyboard shortcuts"),
                "Esc: back"),
        }
        kb = self._key_bindings()
        self.app = Application(
            layout=Layout(DynamicContainer(lambda: self.views[self.screen]),
                          focused_element=self.menu),
            key_bindings=kb,
            full_screen=True,
            mouse_support=False,
            style=Style.from_dict({
                "header": "fg:ansicyan bold",
                "footer": "fg:ansiwhite",
                "hint": "fg:ansibrightblack",
                "frame.border": "fg:ansiblue",
                "radio-list": "fg:ansiwhite",
                "checkbox-list": "fg:ansiwhite",
                "selected-option": "fg:ansicyan bold",
            }),
        )
        self.app.ttimeoutlen = 0.08  # Esc should feel immediate, not wait 0.5s.
        self._bind_choice(self.menu, self.open_menu, radio=True, home=True)

    def _bind_choice(self, widget, on_enter, *, radio=False, home=False, selector=False, confirm=False) -> None:
        """List controls capture Enter and Keys.Any before application bindings."""
        bindings = widget.control.key_bindings

        @bindings.add("enter")
        def _enter(_event):
            if radio:
                widget._handle_enter()  # Commit highlighted radio option.
            on_enter()

        @bindings.add("escape")
        def _back(_event):
            self.back()

        @bindings.add("?")
        def _help(_event):
            self._show_help()

        @bindings.add("c-q")
        def _quit(_event):
            self.quit()

        if home:
            @bindings.add("q")
            def _quit_home(_event):
                self.quit()

        if selector:
            @bindings.add("a")
            def _all(_event):
                widget.current_values = list(ORDER)
                self._notice("All components selected.")

            @bindings.add("n")
            def _none(_event):
                widget.current_values = []
                self._notice("Selection cleared.")

        if confirm:
            @bindings.add("d")
            def _dry(_event):
                self.toggle_dry_run()

    def _show_help(self) -> None:
        self.help_return_screen = self.screen
        self.navigate("help", self.help_view)

    def _page(self, title: str, body, hint: str):
        return HSplit([
            Label(lambda: " DEVBOX  /  " + title, style="class:header"),
            body,
            Label(lambda: " " + self.message, style="class:footer"),
            Label(" " + hint, style="class:hint"),
        ])

    def _make_selector(self) -> CheckboxList:
        group_names = {code: group for group, codes in GROUPS for code in codes}
        values = [
            (code, f"{label:<25} [{self.available[code]:<9}]  {group_names[code]}")
            for code, label in COMPONENTS
        ]
        return CheckboxList(values)

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        is_screen = lambda name: Condition(lambda: self.screen == name)

        @kb.add("enter", filter=is_screen("home"))
        def _home(_event):
            self.open_menu()

        @kb.add("enter", filter=is_screen("select"))
        def _select(_event):
            self.confirm_selection()

        @kb.add("enter", filter=is_screen("confirm"))
        def _confirm(_event):
            self.execute_selection()

        @kb.add("enter", filter=is_screen("logs"))
        def _history(_event):
            self.open_history()

        @kb.add("enter", filter=is_screen("result"))
        def _done(_event):
            self.navigate("home", self.menu)

        @kb.add("a", filter=is_screen("select"))
        def _all(_event):
            self.selector.current_values = list(ORDER)
            self._notice("All components selected.")

        @kb.add("n", filter=is_screen("select"))
        def _none(_event):
            self.selector.current_values = []
            self._notice("Selection cleared.")

        @kb.add("d", filter=is_screen("confirm"))
        def _dry(_event):
            self.toggle_dry_run()

        @kb.add("l", filter=is_screen("result"))
        def _log(_event):
            self.show_full_log()

        @kb.add("o", filter=is_screen("view_log"))
        def _pager(_event):
            asyncio.create_task(self._external_pager())

        @kb.add("escape")
        def _back(_event):
            self.back()

        @kb.add("?", filter=Condition(lambda: self.screen != "help"))
        def _help(_event):
            self._show_help()

        @kb.add("q", filter=is_screen("home"))
        @kb.add("c-q")
        def _quit(_event):
            self.quit()

        return kb

    def navigate(self, screen: str, focus=None) -> None:
        self.screen = screen
        if focus is not None:
            self.app.layout.focus(focus)
        self.app.invalidate()

    def _notice(self, message: str) -> None:
        self.message = message
        self.app.invalidate()

    def open_menu(self) -> None:
        action = self.menu.current_value
        if action == "exit":
            self.quit()
        elif action in ("install", "upgrade"):
            self.action = action
            self.available = inventory()
            self.selector = self._make_selector()
            self._bind_choice(self.selector, self.confirm_selection, selector=True)
            self.views["select"] = self._page(
                "COMPONENTS", Frame(self.selector, title=f"{action.title()} tools (Space)"),
                "Space: toggle   A: all   N: none   Enter: next   Esc: back")
            self._notice(f"Select tools to {action}. Installed-state is informational.")
            self.navigate("select", self.selector)
        elif action == "logs":
            self.list_history()
        elif action == "update":
            self.action = action
            self.selected = []
            self.auto_added = []
            self._make_confirmation()
        else:
            self.start(action)

    def confirm_selection(self) -> None:
        selected = list(self.selector.current_values)
        if not selected:
            self._notice("Select at least one component using Space.")
            return
        if self.action == "install":
            selected, extra = with_dependencies(selected, self.available)
        else:
            extra = []
        self.selected, self.auto_added = selected, extra
        self._make_confirmation()

    def _make_confirmation(self) -> None:
        options: list[tuple[str, str]] = []
        if self.action == "install":
            if "zsh" in self.selected:
                options.append(("change_shell", "Set Zsh as default login shell"))
            if "docker" in self.selected:
                options.append(("docker_group", "Add current user to docker group (root-equivalent)"))
            if "keychain" in self.selected:
                options.append(("ssh_key", "If needed, generate an Ed25519 key WITHOUT a passphrase"))
        self.options = CheckboxList(options or [("placeholder", "No optional changes")])
        self._bind_choice(self.options, self.execute_selection, confirm=True)
        self.views["confirm"] = self._page(
            "CONFIRM", VSplit([
                Frame(Label(lambda: self._selection_summary()), title="Plan",
                      width=Dimension(weight=2)),
                Frame(self.options, title="Optional changes (default OFF)",
                      width=Dimension(weight=3)),
            ], padding=1),
            "Space: optional choice   D: dry-run   Enter: run   Esc: back")
        self._notice("Review the plan. Optional changes are OFF by default.")
        self.navigate("confirm", self.options)

    def _selection_summary(self) -> str:
        if self.action == "update":
            return "Update Devbox source\nFast-forward only\n\nRestart TUI afterward."
        added = f"\nAuto-added: {', '.join(self.auto_added)}" if self.auto_added else ""
        mode = "DRY RUN (no installation)" if self.dry_run else "REAL EXECUTION"
        return f"{self.action.title()}: {len(self.selected)} component(s)\n{mode}\n\n" + \
            "\n".join(self.selected) + added

    def toggle_dry_run(self) -> None:
        if self.busy:
            self._notice("Cannot change preview while a task is active.")
            return
        self.dry_run = not self.dry_run
        self._notice("Dry-run ON: no changes will be made." if self.dry_run
                     else "Dry-run OFF: changes will be applied.")

    def execute_selection(self) -> None:
        action = self.action
        if action == "update":
            self.start(action)
        else:
            self.start(action, self.selected)

    def start(self, action: str, selected: list[str] | None = None) -> None:
        if self.busy:
            self._notice("An operation is already active.")
            return
        chosen = list(self.selector.current_values) if selected is None and action in ("install", "upgrade") else list(selected or [])
        try:
            command = build_command(action, chosen, dry_run=self.dry_run)
        except ValueError as exc:
            self._notice(str(exc))
            return

        # Reserve the job slot before creating the task: two rapid Enter presses
        # must not start overlapping APT/dpkg operations.
        self.busy = True
        self.current_action = action.title()
        self.status = {code: ("QUEUED" if code in chosen else "--") for code in ORDER}
        self.log_path = None
        self.event_path = None
        self.event_offset = 0
        self.last_code = None
        self.last_result = "Preparing..."
        self.status_view.text = self._render_status()
        self.log_view.text = "Preparing job..."
        self._notice(f"Starting {action}...")
        self.navigate("run", self.status_view)
        self.run_task = asyncio.create_task(self._run(action, command, chosen))

    async def _authorize_sudo(self) -> bool:
        if not shutil.which("sudo"):
            self._notice("sudo is unavailable. Install/upgrade requires sudo.")
            return False
        self._notice("Authenticating sudo in the terminal...")
        async with in_terminal():
            proc = await asyncio.create_subprocess_exec("sudo", "-v")
            code = await proc.wait()
        if code != 0:
            self._notice("sudo authentication failed or was cancelled.")
        return code == 0

    async def _sudo_keepalive(self) -> None:
        while self.busy:
            await asyncio.sleep(45)
            if not self.busy:
                return
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-n", "-v", stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            if await proc.wait() != 0:
                self._notice("sudo session expired; privileged steps may fail.")
                return

    async def _run(self, action: str, command: list[str], selected: list[str]) -> None:
        keepalive: asyncio.Task[None] | None = None
        code: int | None = None
        try:
            if action in ("install", "upgrade") and not self.dry_run:
                if not await self._authorize_sudo():
                    code = 1
                    self.last_result = "Cannot start: sudo authentication not completed."
                    return
                keepalive = asyncio.create_task(self._sudo_keepalive())

            log_dir = STATE_ROOT / "logs"
            event_dir = STATE_ROOT / "runs"
            log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            event_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            fd, name = tempfile.mkstemp(prefix=f"{stamp}-{action}-", suffix=".log", dir=log_dir)
            self.log_path = Path(name)
            event_fd, event_name = tempfile.mkstemp(
                prefix=f"{stamp}-{action}-", suffix=".events", dir=event_dir)
            os.close(event_fd)
            self.event_path = Path(event_name)
            env = os.environ.copy()
            env["DEVBOX_EVENT_FILE"] = str(self.event_path)
            env["DEVBOX_TUI_MODE"] = "1"
            enabled = set(self.options.current_values) if action == "install" else set()
            for key, option in (
                ("DEVBOX_CONFIRM_CHANGE_SHELL", "change_shell"),
                ("DEVBOX_CONFIRM_DOCKER_GROUP", "docker_group"),
                ("DEVBOX_CONFIRM_SSH_KEY", "ssh_key"),
                ("DEVBOX_CONFIRM_KUBECTL_REPLACE", "kubectl_replace"),
            ):
                env[key] = "yes" if option in enabled else "no"
            with os.fdopen(fd, "wb", buffering=0) as output:
                self.process = await asyncio.create_subprocess_exec(
                    *command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT)
                self._notice(f"{action.title()} running. Log: {self.log_path}")
                while self.process.returncode is None:
                    await asyncio.sleep(0.3)
                    self._refresh()
                code = await self.process.wait()
            self._refresh()
            self.last_result = ("Completed successfully." if code == 0
                                else f"Failed with exit code {code}.")
            if action == "update" and code == 0:
                self.last_result += " Restart TUI to load the new source."
        except Exception as exc:
            code = 1
            self.last_result = f"Cannot execute {action}: {exc}"
        finally:
            if keepalive is not None:
                keepalive.cancel()
                try:
                    await keepalive
                except asyncio.CancelledError:
                    pass
            self.process = None
            self.busy = False
            self.last_code = code
            if code != 0:
                for component in selected:
                    if self.status[component] in ("RUNNING", "QUEUED"):
                        self.status[component] = ("FAILED" if self.status[component] == "RUNNING"
                                                  else "NOT_RUN")
            self._render_result()
            self._notice(self.last_result)
            self.navigate("result", self.results_view)

    def _render_status(self) -> str:
        rows = [f"  {self.current_action or 'Idle'}", ""]
        for code in ORDER:
            if self.status[code] != "--":
                rows.append(f"  {code:<16} {self.status[code]}")
        return "\n".join(rows) if len(rows) > 2 else "Waiting for status events..."

    def _refresh(self) -> None:
        events, self.event_offset = read_events(self.event_path, self.event_offset)
        for name, state in events:
            if name in self.status:
                self.status[name] = state
        self.status_view.text = self._render_status()
        self.log_view.text = log_tail(self.log_path)
        self.app.invalidate()

    def _render_result(self) -> None:
        lines = [f"{self.current_action}: {self.last_result}", "", self._render_status(),
                 "", f"Full log: {self.log_path or '(not created)'}", "", "LAST OUTPUT",
                 log_tail(self.log_path, count=22)]
        self.results_view.text = "\n".join(lines)

    def list_history(self) -> None:
        log_dir = STATE_ROOT / "logs"
        paths = sorted(log_dir.glob("*.log"), reverse=True)[:100] if log_dir.exists() else []
        self.log_files = RadioList([(str(p), p.name) for p in paths] or
                                   [("", "No saved logs yet.")])
        self._bind_choice(self.log_files, self.open_history, radio=True)
        self.views["logs"] = self._page(
            "LOG HISTORY", Frame(self.log_files, title="Recent runs (newest first)"),
            "Enter: open log   Esc: main menu")
        self._notice(f"{len(paths)} recent log(s).")
        self.navigate("logs", self.log_files)

    def open_history(self) -> None:
        value = self.log_files.current_value
        if not value:
            self._notice("No history available.")
            return
        self._show_log(Path(value), "logs")

    def _show_log(self, path: Path, previous: str) -> None:
        self.log_path = path
        self.previous_screen = previous
        self.history_view.text = log_preview(path)
        self._notice(f"Log: {path}")
        self.navigate("view_log", self.history_view)

    def show_full_log(self) -> None:
        if self.log_path is None:
            self._notice("No log has been created yet.")
            return
        if self.busy:
            self._notice("Log viewer becomes available when the task finishes.")
            return
        self._show_log(self.log_path, self.screen)

    async def _external_pager(self) -> None:
        if self.log_path is None:
            return
        pager = shutil.which("less") or shutil.which("more")
        if pager is None:
            self._notice("No external pager found. Use the built-in log viewer.")
            return
        async with in_terminal():
            argv = [pager, "-R", str(self.log_path)] if Path(pager).name == "less" else [pager, str(self.log_path)]
            proc = await asyncio.create_subprocess_exec(*argv)
            await proc.wait()

    def back(self) -> None:
        if self.busy:
            self._notice("A job is running; leaving would orphan the installer.")
            return
        if self.screen == "help":
            target = self.help_return_screen
            self.navigate(target, self._focus_for(target))
        elif self.screen == "view_log":
            target = self.previous_screen
            self.navigate(target, self._focus_for(target))
        elif self.screen == "confirm":
            self.navigate("select", self.selector) if self.action != "update" else self.navigate("home", self.menu)
        elif self.screen in ("select", "result", "logs"):
            self.navigate("home", self.menu)

    def _focus_for(self, screen: str):
        return {
            "home": self.menu, "select": self.selector, "confirm": self.options,
            "result": self.results_view, "logs": self.log_files,
            "view_log": self.history_view, "run": self.status_view,
        }.get(screen, self.menu)

    def quit(self) -> None:
        if self.busy:
            self._notice("Finish the running task before exiting.")
            return
        self.app.exit()

    def run(self) -> None:
        asyncio.run(self.app.run_async())


def main() -> None:
    DevboxTUI().run()


if __name__ == "__main__":
    main()
