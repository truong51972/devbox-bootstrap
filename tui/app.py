"""Devbox: keyboard-first setup and maintenance console.

Pure presentation lives in tui.ui. The existing Bash commands, event protocol,
permission model and on-disk logs remain unchanged.
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
from prompt_toolkit.layout import HSplit, VSplit, DynamicContainer, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from tui.backend import (
    ROOT, STATE_ROOT, FINAL_STATES, build_command, log_tail, log_preview,
    read_events,
)
from tui.catalog import COMPONENTS, GROUPS, ORDER, DEPENDENCIES, inventory, with_dependencies
from tui.ui import Entry, KeyboardList, THEMES, STATUS_STYLES

FINISHED_STATES = FINAL_STATES
MENU = (
    ("install", "Install components"),
    ("upgrade", "Upgrade components"),
    ("doctor", "Doctor - check configuration"),
    ("preflight", "Preflight - inspect host"),
    ("update", "Update Devbox source"),
    ("logs", "Logs and history"),
    ("exit", "Exit"),
)
MENU_GROUPS = {
    "install": "SETUP", "upgrade": "SETUP", "doctor": "SYSTEM",
    "preflight": "SYSTEM", "update": "MAINTENANCE", "logs": "MAINTENANCE",
    "exit": "MAINTENANCE",
}
MENU_DETAILS = {
    "install": "Choose development tools and install only what you need.",
    "upgrade": "Update selected tools without changing Devbox source.",
    "doctor": "Check binaries, services, permissions and configuration.",
    "preflight": "Inspect the system before attempting installation.",
    "update": "Fast-forward Devbox source and restart the application.",
    "logs": "Review past operations and their complete terminal output.",
    "exit": "Leave Devbox without modifying the system.",
}
DESCRIPTIONS = {
    "zsh": "Interactive shell with Oh My Zsh configuration.",
    "powerlevel10k": "Fast customizable Zsh prompt. Depends on Zsh.",
    "uv": "Python interpreter, virtual environment and package manager.",
    "keychain": "SSH key agent and shell integration.",
    "zoxide": "Smarter directory jumping for your terminal.",
    "fzf": "Fuzzy finder for files, history and commands.",
    "ripgrep": "Fast recursive text search (rg).",
    "bat-fd": "Syntax-highlighted cat and quick filesystem discovery.",
    "docker": "Docker Engine and command-line tooling.",
    "nvidia": "Enable NVIDIA GPU support for Docker containers.",
    "kubectl": "Kubernetes command-line client.",
    "minikube": "Local Kubernetes environment.",
    "direnv": "Directory-specific environment variables.",
}
WARNINGS = {
    "docker": "Docker group access grants root-equivalent privileges.",
    "nvidia": "NVIDIA integration may restart the Docker service.",
    "keychain": "Optional key generation produces a key without a passphrase.",
    "zsh": "Changing the login shell affects future terminal sessions.",
}
HELP = """NAVIGATION
  Up/Down or j/k     Move highlight
  Enter              Open selection or continue
  Esc                Back / close search / return
  ?                  Keyboard help

COMPONENT SELECTION
  Space              Toggle highlighted component
  a / n              Select visible / clear all
  /                  Filter by tool or group
  i                  Show full component details
  Esc (in filter)    Clear filter and return to list

CONFIRMATION
  Space              Toggle an optional change
  d                  Toggle dry-run
  Enter              Start the selected action

EXECUTION / RESULTS
  l                  View saved log (after completion)
  o                  Open external pager from log viewer
  PageUp/PageDown    Scroll text and logs
  t                  Toggle minimalist / monochrome theme (home)
  q                  Exit on home screen only

Changes that require explicit consent are OFF by default.
Full logs are under ~/.local/state/devbox-bootstrap/logs.
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
        self.message = "Ready. Choose an action."
        self.process: asyncio.subprocess.Process | None = None
        self.log_path: Path | None = None
        self.event_path: Path | None = None
        self.event_offset = 0
        self.last_code: int | None = None
        self.last_result = ""
        self.run_task: asyncio.Task[None] | None = None
        self.filter_active = False
        self.theme = os.environ.get("DEVBOX_THEME", "minimal").lower()
        if self.theme not in THEMES:
            self.theme = "minimal"
        self.expanded_log = False
        self._search_text = ""

        self.menu = self._make_menu()
        self.selector = self._make_selector()
        self.options = self._make_options([])
        self.log_files = self._make_log_list([])
        self.status_view = TextArea(
            text="", read_only=True, focusable=True, scrollbar=True,
            wrap_lines=False,
        )
        self.log_view = TextArea(
            text="", read_only=True, focusable=False, scrollbar=True,
            wrap_lines=False,
        )
        self.results_view = TextArea(
            text="", read_only=True, focusable=True, scrollbar=True,
            wrap_lines=False,
        )
        self.history_view = TextArea(
            text="", read_only=True, focusable=True, scrollbar=True,
            wrap_lines=False,
        )
        self.help_view = TextArea(
            text=HELP, read_only=True, focusable=True, scrollbar=True,
            wrap_lines=False,
        )
        self.info_view = TextArea(
            text="", read_only=True, focusable=True, scrollbar=True,
            wrap_lines=True,
        )
        self.filter_input = TextArea(
            text="", multiline=False, prompt=" / Filter: ",
            accept_handler=lambda _buffer: self._finish_filter(),
        )
        self.filter_input.buffer.on_text_changed += self._filter_changed

        self._bind_text(self.status_view)
        self._bind_text(self.results_view, result=True)
        self._bind_text(self.history_view, log_viewer=True)
        self._bind_text(self.help_view)
        self._bind_text(self.info_view)
        self._bind_filter()

        self.views: dict[str, object] = {}
        self._build_views()

        self.app = Application(
            layout=Layout(
                DynamicContainer(lambda: self.views[self.screen]),
                focused_element=self.menu.window,
            ),
            key_bindings=self._key_bindings(),
            full_screen=True,
            mouse_support=False,
            style=Style.from_dict(THEMES[self.theme]),
        )
        self.app.ttimeoutlen = 0.08
        self.app.timeoutlen = 0.10

    def columns(self) -> int:
        try:
            return self.app.output.get_size().columns
        except (AttributeError, ValueError):
            return 80

    def rows(self) -> int:
        try:
            return self.app.output.get_size().rows
        except (AttributeError, ValueError):
            return 24

    def _make_menu(self) -> KeyboardList:
        return KeyboardList(
            [
                Entry(key, label, MENU_GROUPS[key], description=MENU_DETAILS[key])
                for key, label in MENU
            ],
            on_enter=self.open_menu,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._invalidate,
            on_quit=self.quit,
            on_theme=self.toggle_theme,
            get_columns=self.columns,
        )

    def _make_selector(self) -> KeyboardList:
        groups = {code: name for name, codes in GROUPS for code in codes}
        return KeyboardList(
            [
                Entry(code, label, groups.get(code, ""), self.available[code],
                      DESCRIPTIONS.get(code, "Developer tool"))
                for code, label in COMPONENTS
            ],
            multiple=True,
            on_enter=self.confirm_selection,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._invalidate,
            on_filter=self._begin_filter,
            on_details=self._show_component_info,
            get_columns=self.columns,
        )

    def _make_options(self, entries: list[Entry]) -> KeyboardList:
        return KeyboardList(
            entries,
            multiple=True,
            on_enter=self.execute_selection,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._invalidate,
            on_dry=self.toggle_dry_run,
            get_columns=self.columns,
        )

    def _make_log_list(self, paths: list[Path]) -> KeyboardList:
        return KeyboardList(
            [Entry(str(p), p.name, "", description=str(p)) for p in paths],
            on_enter=self.open_history,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._invalidate,
            get_columns=self.columns,
        )

    def _invalidate(self) -> None:
        if hasattr(self, "app"):
            self.app.invalidate()

    def _text(self, render, *, height=None):
        return Window(
            content=FormattedTextControl(render, focusable=False, show_cursor=False),
            height=height, wrap_lines=True, style="class:body",
        )

    def _divider(self):
        return Window(height=1, char="─", style="class:divider")

    def _page(self, title: str, body, shortcut: str):
        header = self._text(
            lambda: [
                ("class:header", "  DEVBOX "),
                ("class:muted", " / " + title.upper()),
                ("class:muted", "     Ubuntu / WSL"),
            ],
            height=1,
        )
        notice = self._text(
            lambda: [("class:statusbar", "  " + self.message)], height=1
        )
        footer = self._text(
            lambda: [("class:footer", "  " + shortcut)], height=1
        )
        return HSplit([
            header, self._divider(), body, notice, footer,
        ])

    def _build_views(self) -> None:
        self.views["home"] = self._page(
            "Main menu",
            DynamicContainer(self._home_layout),
            "↑↓/j/k Navigate   Enter Open   t Theme   ? Help   q Quit",
        )
        self.views["select"] = self._page(
            "Components",
            HSplit([
                DynamicContainer(self._selection_layout),
                DynamicContainer(lambda: self._filter_layout()),
            ]),
            "↑↓ Move   Space Select   a All   n None   / Filter   i Info   Enter Next   Esc Back",
        )
        self.views["confirm"] = self._page(
            "Confirm", DynamicContainer(self._confirm_layout),
            "Space Toggle options   d Dry-run   Enter Execute   Esc Back",
        )
        self.views["run"] = self._page(
            "Execution", DynamicContainer(self._run_layout),
            "l Expand/collapse output   Task active · exit locked",
        )
        self.views["result"] = self._page(
            "Result", self.results_view,
            "l View log   Enter Home   Esc Home   ? Help",
        )
        self.views["logs"] = self._page(
            "History", DynamicContainer(self._logs_layout),
            "↑↓/j/k Browse   Enter View log   Esc Back",
        )
        self.views["view_log"] = self._page(
            "Log viewer", self.history_view,
            "↑↓/PgUp/PgDn Scroll   o External pager   Esc Back",
        )
        self.views["help"] = self._page(
            "Keyboard help", self.help_view, "Esc Back",
        )
        self.views["info"] = self._page(
            "Component details", self.info_view,
            "Esc Back to components",
        )

    def _home_layout(self):
        if self.columns() >= 94:
            return VSplit([
                self.menu.window,
                self._divider_v(),
                self._text(self._home_details),
            ], padding=2)
        if self.rows() >= 26:
            return HSplit([
                self.menu.window,
                self._divider(),
                self._text(self._home_details, height=5),
            ])
        return self.menu.window

    def _divider_v(self):
        return Window(char="│", width=1, style="class:divider")

    def _selection_layout(self):
        if self.columns() >= 94:
            return VSplit([
                self.selector.window,
                self._divider_v(),
                self._text(self._component_details),
            ], padding=1)
        if self.rows() >= 25 and self.columns() >= 64:
            return HSplit([
                self.selector.window,
                self._divider(),
                self._text(self._component_details, height=6),
            ])
        return self.selector.window

    def _filter_layout(self):
        from prompt_toolkit.layout import ConditionalContainer
        return ConditionalContainer(
            content=self.filter_input,
            filter=Condition(lambda: self.filter_active),
        )

    def _confirm_layout(self):
        # A compact summary and context-specific options, not two huge frames.
        return HSplit([
            self._text(self._confirm_tokens, height=Dimension(min=5, weight=2)),
            self._divider(),
            self._text(lambda: [
                ("class:section", "  OPTIONAL CHANGES (OFF BY DEFAULT)"),
                ("", "\n"),
            ], height=2),
            self.options.window,
        ])

    def _run_layout(self):
        if self.expanded_log:
            return HSplit([
                self._text(self._progress_tokens, height=2),
                self.status_view,
                self._divider(),
                self._text(lambda: [("class:section", "  EXPANDED OUTPUT")], height=1),
                self.log_view,
            ])
        return HSplit([
            self._text(self._progress_tokens, height=2),
            self.status_view,
            self._divider(),
            self._text(lambda: [("class:section", "  RECENT OUTPUT")], height=1),
            self.log_view,
        ])

    def _logs_layout(self):
        if self.columns() >= 94:
            return VSplit([
                self.log_files.window,
                self._divider_v(),
                self._text(self._history_details),
            ], padding=1)
        return self.log_files.window

    def _home_details(self):
        item = self.menu.current
        if item is None:
            return [("class:muted", "  No action selected")]
        return [
            ("class:section", "  SELECTED ACTION\n\n"),
            ("class:title", "  " + item.label + "\n\n"),
            ("class:body", "  " + item.description + "\n\n"),
            ("class:muted", "  Enter to continue"),
        ]

    def _component_details(self):
        item = self.selector.current
        if item is None:
            return [("class:muted", "  No matching component")]
        selected = len(self.selector.selected)
        deps = DEPENDENCIES.get(item.key, ())
        out = [
            ("class:section", "  COMPONENT DETAILS\n\n"),
            ("class:title", "  " + item.label + "\n\n"),
            ("class:body", "  " + item.description + "\n\n"),
            ("class:muted", "  State: "),
            (STATUS_STYLES.get(item.status, "class:body"), item.status + "\n"),
            ("class:muted", "  Requires: "),
            ("class:body", (", ".join(deps) or "None") + "\n\n"),
            ("class:muted", f"  {selected} selected"),
        ]
        if item.key in WARNINGS:
            out.extend([
                ("class:warning", "\n\n  NOTE  "),
                ("class:body", WARNINGS[item.key]),
            ])
        return out

    def _confirm_tokens(self):
        lines = self._selection_summary().splitlines()
        tokens = [
            ("class:section", "  EXECUTION PLAN\n\n"),
        ]
        for index, line in enumerate(lines):
            if "DRY RUN" in line:
                style = "class:warning"
            elif index == 0:
                style = "class:title"
            elif "Auto-added:" in line:
                style = "class:warning"
            else:
                style = "class:body"
            tokens.append((style, "  " + line + "\n"))
        if not self.options.entries:
            tokens.append(("class:muted", "\n  No extra permissions requested."))
        return tokens

    def _progress_tokens(self):
        active = [code for code in ORDER if self.status.get(code) != "--"]
        complete = [
            code for code in active if self.status[code] in FINAL_STATES
        ]
        running = [
            code for code in active if self.status[code] == "RUNNING"
        ]
        current = running[0] if running else self.current_action
        if not active:
            return [
                ("class:running", "  " + self.current_action.upper() + "\n"),
                ("class:muted", "  Running system command..."),
            ]
        return [
            ("class:running", f"  {self.current_action.upper()} "),
            ("class:muted", f" {len(complete)} / {len(active)} complete\n"),
            ("class:body", "  Current: " + current),
        ]

    def _history_details(self):
        item = self.log_files.current
        if item is None:
            return [("class:muted", "  No logs found.")]
        return [
            ("class:section", "  SELECTED RUN\n\n"),
            ("class:title", "  " + item.label + "\n\n"),
            ("class:muted", "  Enter to open this log."),
        ]

    def _show_component_info(self) -> None:
        self.info_view.text = "".join(text for _style, text in self._component_details())
        self.navigate("info", self.info_view)

    def _begin_filter(self) -> None:
        self.filter_active = True
        self.app.layout.focus(self.filter_input)
        self._notice("Filter by name, group or description. Enter to return.")
        self._invalidate()

    def _filter_changed(self, _buffer) -> None:
        self.selector.set_query(self.filter_input.text)

    def _finish_filter(self) -> bool:
        self.filter_active = False
        self.app.layout.focus(self.selector.window)
        self._notice("Filtered selection. Esc returns to the main menu.")
        return True

    def _cancel_filter(self) -> None:
        self.filter_input.text = ""
        self.selector.set_query("")
        self._finish_filter()

    def _bind_filter(self) -> None:
        kb = KeyBindings()

        @kb.add("escape")
        def _escape(_event) -> None:
            self._cancel_filter()

        @kb.add("c-q")
        def _quit(_event) -> None:
            self.quit()

        self.filter_input.control.key_bindings = kb

    def _bind_text(self, widget, *, result=False, log_viewer=False) -> None:
        kb = KeyBindings()

        @kb.add("escape")
        def _back(_event):
            self.back()

        @kb.add("c-q")
        def _quit(_event):
            self.quit()

        @kb.add("?")
        def _help(_event):
            if self.screen != "help":
                self._show_help()

        if widget is self.status_view:
            @kb.add("l")
            def _expand(_event):
                self.expanded_log = not self.expanded_log
                self.log_view.text = log_tail(
                    self.log_path, count=25 if self.expanded_log else 10
                )
                self._invalidate()

        if result:
            @kb.add("enter")
            def _home(_event):
                self.navigate("home", self.menu.window)

            @kb.add("l")
            def _log(_event):
                self.show_full_log()

        if log_viewer:
            @kb.add("o")
            def _pager(_event):
                asyncio.create_task(self._external_pager())

        widget.control.key_bindings = kb

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape")
        def _back(_event):
            self.back()

        @kb.add("c-q")
        def _quit(_event):
            self.quit()

        @kb.add("?", filter=Condition(lambda: self.screen != "help"))
        def _help(_event):
            self._show_help()

        return kb

    def _show_help(self) -> None:
        if self.busy:
            self._notice("Help is available when the task has finished.")
            return
        self.help_return_screen = self.screen
        self.navigate("help", self.help_view)

    def navigate(self, screen: str, focus=None) -> None:
        self.screen = screen
        if focus is not None:
            self.app.layout.focus(focus)
        self._invalidate()

    def _notice(self, message: str) -> None:
        self.message = message
        self._invalidate()

    def toggle_theme(self) -> None:
        self.theme = "mono" if self.theme == "minimal" else "minimal"
        self.app.style = Style.from_dict(THEMES[self.theme])
        self._notice(f"Theme: {self.theme}. Set DEVBOX_THEME={self.theme} to keep it on launch.")

    def open_menu(self) -> None:
        action = self.menu.current_value
        if action == "exit":
            self.quit()
        elif action in ("install", "upgrade"):
            self.action = action
            self.available = inventory()
            self.selector = self._make_selector()
            self.filter_active = False
            self.filter_input.text = ""
            self._notice(f"Select tools to {action}. Space toggles the highlighted row.")
            self.navigate("select", self.selector.window)
        elif action == "logs":
            self.list_history()
        elif action == "update":
            self.action = action
            self.selected = []
            self.auto_added = []
            self._make_confirmation()
        elif action is not None:
            self.start(action)

    def confirm_selection(self) -> None:
        selected = self.selector.current_values
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
        options: list[Entry] = []
        if self.action == "install":
            if "zsh" in self.selected:
                options.append(Entry("change_shell", "Set Zsh as login shell"))
            if "docker" in self.selected:
                options.append(Entry("docker_group", "Join docker group (root-equivalent)"))
            if "keychain" in self.selected:
                options.append(Entry("ssh_key", "Generate unencrypted Ed25519 key if needed"))
        self.options = self._make_options(options)
        self._notice("Review the plan. Optional changes are OFF by default.")
        self.navigate("confirm", self.options.window)

    def _selection_summary(self) -> str:
        if self.action == "update":
            return "Update Devbox source\nFast-forward only\nRestart the TUI after updating."
        added = f"\nAuto-added: {', '.join(self.auto_added)}" if self.auto_added else ""
        mode = "DRY RUN (no installation)" if self.dry_run else "REAL EXECUTION"
        chosen = self.selected[:5]
        details = "\n".join(chosen)
        if len(self.selected) > len(chosen):
            details += f"\n...and {len(self.selected) - len(chosen)} more"
        warnings = []
        if "nvidia" in self.selected:
            warnings.append("NVIDIA setup may restart Docker")
        if "docker" in self.selected and self.action == "upgrade":
            warnings.append("Docker upgrade may restart containers")
        note = "\n" + "\n".join(warnings) if warnings else ""
        return f"{self.action.title()}: {len(self.selected)} component(s)\n{mode}\n" + details + added + note

    def toggle_dry_run(self) -> None:
        if self.action == "update":
            self._notice("Devbox source update cannot be dry-run in the TUI.")
            return
        if self.busy:
            self._notice("Cannot change preview while a task is active.")
            return
        self.dry_run = not self.dry_run
        self._notice("Dry-run ON: no changes will be made." if self.dry_run
                     else "Dry-run OFF: changes will be applied.")

    def execute_selection(self) -> None:
        self.start(self.action, self.selected if self.action != "update" else [])

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

        # Reserve the slot before creating a task: rapid Enter cannot overlap APT.
        self.busy = True
        self.current_action = action.title()
        self.status = {code: ("QUEUED" if code in chosen else "--") for code in ORDER}
        self.log_path = None
        self.event_path = None
        self.event_offset = 0
        self.last_code = None
        self.last_result = "Preparing..."
        self.expanded_log = False
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
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
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
                prefix=f"{stamp}-{action}-", suffix=".events", dir=event_dir
            )
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
                    stdout=output, stderr=subprocess.STDOUT,
                )
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
                value = self.status[code]
                marker = "✓" if value in {"INSTALLED", "CONFIGURED", "UPDATED", "UP_TO_DATE"} else (
                    "!" if value == "FAILED" else ">" if value == "RUNNING" else "·"
                )
                rows.append(f"  {marker}  {code:<16} {value}")
        return "\n".join(rows) if len(rows) > 2 else "Waiting for status events..."

    def _refresh(self) -> None:
        events, self.event_offset = read_events(self.event_path, self.event_offset)
        for name, state in events:
            if name in self.status:
                self.status[name] = state
        self.status_view.text = self._render_status()
        self.log_view.text = log_tail(
            self.log_path, count=25 if self.expanded_log else 10
        )
        self._invalidate()

    def _render_result(self) -> None:
        heading = "SUCCESS" if self.last_code == 0 else "FAILED"
        lines = [f"  {heading} — {self.current_action}: {self.last_result}", "",
                 self._render_status(), "", f"  Full log: {self.log_path or '(not created)'}",
                 "", "  LAST OUTPUT", log_tail(self.log_path, count=22)]
        self.results_view.text = "\n".join(lines)

    def list_history(self) -> None:
        log_dir = STATE_ROOT / "logs"
        paths = sorted(log_dir.glob("*.log"), reverse=True)[:100] if log_dir.exists() else []
        self.log_files = self._make_log_list(paths)
        self._notice(f"{len(paths)} recent run log(s).")
        self.navigate("logs", self.log_files.window)

    def open_history(self) -> None:
        value = self.log_files.current_value
        if not value:
            self._notice("No log is available.")
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
            self._notice("Full logs are available once the operation ends.")
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
            argv = ([pager, "-R", str(self.log_path)]
                    if Path(pager).name == "less" else [pager, str(self.log_path)])
            proc = await asyncio.create_subprocess_exec(*argv)
            await proc.wait()

    def back(self) -> None:
        if self.busy:
            self._notice("A task is running; leaving would orphan the installer.")
            return
        if self.screen == "help":
            target = self.help_return_screen
            self.navigate(target, self._focus_for(target))
        elif self.screen == "view_log":
            target = self.previous_screen
            self.navigate(target, self._focus_for(target))
        elif self.screen == "confirm":
            self.navigate("select", self.selector.window) if self.action != "update" else self.navigate("home", self.menu.window)
        elif self.screen == "info":
            self.navigate("select", self.selector.window)
        elif self.screen == "select" and self.filter_active:
            self._cancel_filter()
        elif self.screen in ("select", "result", "logs"):
            self.navigate("home", self.menu.window)

    def _focus_for(self, screen: str):
        return {
            "home": self.menu.window, "select": self.selector.window,
            "confirm": self.options.window, "result": self.results_view,
            "logs": self.log_files.window, "view_log": self.history_view,
            "run": self.status_view, "info": self.info_view,
        }.get(screen, self.help_view)

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
