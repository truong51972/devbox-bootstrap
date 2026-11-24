"""Devbox: keyboard-first setup and maintenance console.

Pure presentation lives in tui.ui. The existing Bash commands, event protocol,
permission model and on-disk logs remain unchanged.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
import os
from pathlib import Path
import shutil
import subprocess
import time

from prompt_toolkit import Application
from prompt_toolkit.application import in_terminal
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import DynamicContainer, Layout
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from tui.backend import (
    ROOT, STATE_ROOT, FINAL_STATES, build_command, log_tail, log_preview,
    read_events, read_run_events,
)
from tui.catalog import COMPONENTS, GROUPS, ORDER, DEPENDENCIES, installed, inventory, with_dependencies
from tui.agent_status import AGENTS, LABELS, discover_agents, probe_agent_detail as probe_agent, PluginStatus, summary as ponytail_summary
from tui.ui import Entry, KeyboardList, THEMES, STATUS_STYLES
from tui.update_check import UpdateCheck, check_update
from tui.views import DevboxViews, DETAIL_PANEL_WIDTH
from tui.tasks import BackgroundTasks
from tui.reporting import RunReport, read_report, write_report, summarize_status, status_lines
from tui.execution import prepare_run, run_env, launch, wait_for_run
from tui.inventory_detail import inspect_components
from tui.cleaner import (BY_KEY as CLEANER_ITEMS, SAFE_KEYS, PROBE_GROUPS,
                         PROBE_CONCURRENCY, Scan, probe_group)

FINISHED_STATES = FINAL_STATES
# Stable width across Home, Components and History; remaining columns go to the list.
MENU = (
    ("install", "Install components"),
    ("upgrade", "Upgrade components"),
    ("doctor", "Doctor - check configuration"),
    ("preflight", "Preflight - inspect host"),
    ("clean", "Cleaner - reclaim disk space"),
    ("update", "Update Devbox source"),
    ("logs", "Logs and history"),
    ("exit", "Exit"),
)
MENU_GROUPS = {
    "install": "SETUP", "upgrade": "SETUP", "doctor": "SYSTEM",
    "preflight": "SYSTEM", "clean": "MAINTENANCE", "update": "MAINTENANCE", "logs": "MAINTENANCE",
    "exit": "MAINTENANCE",
}
MENU_DETAILS = {
    "install": "Choose development tools and install only what you need.",
    "upgrade": "Update selected tools without changing Devbox source.",
    "doctor": "Check binaries, services, permissions and configuration.",
    "preflight": "Inspect the system before attempting installation.",
    "clean": "Scan developer caches. All selects safe items only; manual items require consent.",
    "update": "Fast-forward Devbox source, then exit on success.",
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
    "rtk": "Token-saving command proxy. Agent hooks are opt-in.",
    "skills-cli": "Vercel Skills CLI; requires Node.js >= 22.20 and npm.",
    "ponytail": "Ponytail coding-agent plugin; checked against agent plugin inventory.",
}
WARNINGS = {
    "docker": "Docker group access grants root-equivalent privileges.",
    "nvidia": "NVIDIA integration may restart the Docker service.",
    "keychain": "Optional key generation produces a key without a passphrase.",
    "zsh": "Changing the login shell affects future terminal sessions.",
    "rtk": "Selected agent hooks modify user-level agent configuration.",
    "ponytail": "Upstream plugin installs may add executable lifecycle hooks; review before enabling.",
}
AGENT_EXECUTABLES = (
    ("claude", "Claude Code", "claude"),
    ("codex", "Codex", "codex"),
    ("copilot", "Copilot CLI", "copilot"),
    ("opencode", "OpenCode", "opencode"),
    ("gemini", "Gemini CLI", "gemini"),
)
@lru_cache(maxsize=64)
def _cached_log_tail(path: str, size: int, modified_ns: int) -> str:
    """Cache history previews until log size or mtime changes."""
    return log_tail(Path(path), count=5)


HELP = """NAVIGATION
  Up/Down or j/k     Move highlight
  Enter              Open selection or continue
  Esc                Back / close search / return
  ?                  Keyboard help

COMPONENT SELECTION
  Space              Toggle highlighted component
  a / n              Select visible / clear all (Cleaner: all safe, even when filtered)
  /                  Filter by tool or group
  i                  Show full component details
  r                  Refresh agent plugin inventory
  Esc (in filter)    Clear filter and return to list

CONFIRMATION
  Space              Toggle an optional change
  d                  Toggle dry-run (default: apply changes)
  Tab                Switch between plan and options, when present
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


class DevboxTUI(DevboxViews):
    def __init__(self) -> None:
        self.tasks = BackgroundTasks()
        self.run_report: RunReport | None = None
        self.run_started = None
        self.outcome_details: dict[str, str] = {}
        self.component_metadata = {}
        self.screen = "home"
        self.previous_screen = "home"
        self.help_return_screen = "home"
        self.action = ""
        self.current_action = ""
        self.selected: list[str] = []
        self.auto_added: list[str] = []
        # Discovery is PATH-only. No external CLI runs during TUI construction.
        self.ponytail_agents = discover_agents()
        self.ponytail_details: dict[str, PluginStatus] = {}
        self.available = inventory(self.ponytail_agents, quick=True)
        self._agent_scan_task: asyncio.Task[None] | None = None
        self._agent_scan_completed_at = 0.0
        self._agent_scan_generation = 0
        self.status: dict[str, str] = {code: "--" for code in ORDER}
        self.busy = False
        self.dry_run = False
        self.message = "Ready. Choose an action."
        self.update_check_task: asyncio.Task[None] | None = None
        self.pending_update: UpdateCheck | None = None
        self.update_revision = ""
        self.exit_message = ""
        self.process: asyncio.subprocess.Process | None = None
        self.log_path: Path | None = None
        self.event_path: Path | None = None
        self.event_offset = 0
        self.last_code: int | None = None
        self.last_result = ""
        self.run_task: asyncio.Task[None] | None = None
        self.filter_active = False
        self._layout_cache: dict[str, object] = {}
        self.theme = os.environ.get("DEVBOX_THEME", "minimal").lower()
        if self.theme not in THEMES:
            self.theme = "minimal"
        self.expanded_log = False

        self.menu = self._make_menu()
        self.update_choices = KeyboardList(
            [Entry("no", "No — continue without updating"),
             Entry("yes", "Yes — update Devbox and exit")],
            on_enter=self._answer_update, on_back=self._decline_update,
            on_help=self._show_help, on_change=self._invalidate,
            get_columns=self.columns,
        )
        self.selector = self._make_selector()
        self.cleaner_rows: dict[str, Scan] = {}
        self.cleaner_scan_task: asyncio.Task[None] | None = None
        self.cleaner_scan_generation = 0
        self.cleaner_all_requested = False
        self.cleaner_list = self._make_cleaner_list()
        self.options = self._make_options([])
        self.confirm_plan = TextArea(text="", read_only=True, focusable=True,
                                     scrollbar=True, wrap_lines=True)
        self.history_reports = {}
        self.log_files = self._make_log_list([])
        self.status_view = TextArea(
            text="", read_only=True, focusable=True, scrollbar=True,
            wrap_lines=False,
        )
        self.log_view = TextArea(
            text="", read_only=True, focusable=False, scrollbar=True,
            wrap_lines=False,
        )
        self.status_view.window.height = Dimension(weight=3, min=6)
        self.log_view.window.height = Dimension(weight=2, min=5)
        self.results_view = TextArea(
            text="", read_only=True, focusable=True, scrollbar=True,
            wrap_lines=True,
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
        self._bind_text(self.confirm_plan)
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

    def _start_update_check(self) -> None:
        if os.environ.get("DEVBOX_CHECK_UPDATES", "1") == "0":
            return
        self._notice("Checking for Devbox updates...")
        self.update_check_task = self.tasks.start("update", self._check_startup_update())

    def _cancel_update_check(self) -> None:
        if self.update_check_task is not None and not self.update_check_task.done():
            self.tasks.cancel("update")
        self.pending_update = None

    async def _check_startup_update(self) -> None:
        result = await check_update(ROOT)
        if result.state == "available":
            self.pending_update = result
            if self.screen == "home" and not self.busy:
                self._show_update_prompt()
        elif self.screen == "home" and not self.busy:
            message = {
                "current": "Devbox is up to date. Choose an action.",
                "dirty": "Update check skipped: local tracked changes. Choose an action.",
                "unsupported": "Update check skipped for this checkout. Choose an action.",
                "not-fast-forward": "Update check: local history is ahead or diverged.",
            }.get(result.state, "Update check unavailable. Choose an action.")
            self._notice(message)

    def _show_update_prompt(self) -> None:
        if self.pending_update is None or self.busy or self.screen != "home":
            return
        self.update_choices.index = 0
        self._notice("Update available. Choose Yes or No.")
        self.navigate("update_prompt", self.update_choices.window)

    def _update_details(self):
        result = self.pending_update
        if result is None:
            return [("class:muted", "  No update pending.")]
        return [
            ("class:title", "  A new Devbox revision is available.\n\n"),
            ("class:body", f"  Installed: {result.current[:12]}\n"
                           f"  Latest:    {result.latest[:12]}\n"
                           f"  New commits: {result.commits}\n\n"),
            ("class:muted", "  Yes updates source and runtime, then exits.\n"
                            "  Run devbox again to load the new version.\n"
                            "  No continues with the installed version.\n"),
        ]

    def _decline_update(self) -> None:
        self.pending_update = None
        self._notice("Update skipped for this session.")
        self.navigate("home", self.menu.window)

    def _answer_update(self, yes: bool | None = None) -> None:
        if self.screen != "update_prompt" or self.pending_update is None or self.busy:
            return
        if yes is None:
            yes = self.update_choices.current_value == "yes"
        if not yes:
            self._decline_update()
            return
        self.update_revision = self.pending_update.latest
        self.pending_update = None
        self.action = "update"
        self.dry_run = False
        self.selected = []
        self.auto_added = []
        self.start("update", [])

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

    def _component_list_width(self) -> int:
        """List pane width, excluding the fixed detail pane and VSplit spacing."""
        if self.columns() >= 94:
            return max(1, self.columns() - DETAIL_PANEL_WIDTH - 3)
        return self.columns()

    AGENT_SCAN_TTL = 60.0

    def _set_component_status(self, code: str, value: str) -> None:
        # Even an unchanged aggregate may hide newly completed per-agent rows;
        # the right pane must repaint when each probe finishes.
        self.available[code] = value
        for index, entry in enumerate(self.selector.entries):
            if entry.key == code and entry.status != value:
                self.selector.entries[index] = replace(entry, status=value)
                break
        self._invalidate()

    def _refresh_agent_status(self) -> None:
        self.available.update(inventory(self.ponytail_agents, quick=True))
        for code, value in self.available.items():
            self._set_component_status(code, value)
        self._schedule_agent_scan(force=True)

    def _invalidate_agent_scan(self) -> None:
        """Discard in-flight state after an installer may change plugins."""
        self._agent_scan_generation += 1
        self._agent_scan_completed_at = 0.0
        self.ponytail_details.clear()
        self.component_metadata = {}
        if self._agent_scan_task is not None and not self._agent_scan_task.done():
            self.tasks.cancel("agents")
        self._agent_scan_task = None

    def _schedule_agent_scan(self, *, force: bool = False) -> None:
        """Start lazy read-only checks; never block the event loop or redraw."""
        if self._agent_scan_task is not None and not self._agent_scan_task.done():
            if force:
                self._notice("Agent status check already running.")
            return
        if (not force and self._agent_scan_completed_at
                and time.monotonic() - self._agent_scan_completed_at < (
                    10.0 if "Unverified" in self.ponytail_agents.values()
                    else self.AGENT_SCAN_TTL)):
            return

        self.ponytail_agents = discover_agents()
        self.ponytail_details.clear()
        self._set_component_status("ponytail", ponytail_summary(self.ponytail_agents))
        self._set_component_status(
            "rtk", "Unverified" if shutil.which("rtk") or
            (Path.home() / ".local/bin/rtk").is_file() else "Missing",
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Headless/unit tests may manipulate the TUI outside an event loop.
            return
        self._agent_scan_generation += 1
        self._agent_scan_task = self.tasks.start("agents",
            self._scan_agent_status(self._agent_scan_generation)
        )

    async def _scan_agent_status(self, generation: int) -> None:
        """Run bounded blocking checks concurrently in worker threads."""
        async def check_agent(agent: str) -> None:
            try:
                result = await asyncio.to_thread(probe_agent, agent)
            except Exception as exc:
                result = PluginStatus(agent, "Unverified", "inventory", type(exc).__name__)
            if generation != self._agent_scan_generation:
                return
            self.ponytail_details[agent] = result
            self.ponytail_agents[agent] = result.state
            self._set_component_status("ponytail", ponytail_summary(self.ponytail_agents))

        async def check_rtk() -> None:
            try:
                valid = await asyncio.to_thread(installed, "rtk")
            except Exception:
                valid = False
            if generation == self._agent_scan_generation:
                self._set_component_status("rtk", "Installed" if valid else ("Unverified" if shutil.which("rtk") or (Path.home() / ".local/bin/rtk").is_file() else "Missing"))

        tasks = [
            check_agent(agent) for agent in AGENTS
            if self.ponytail_agents.get(agent) == "Checking"
        ]
        tasks.append(check_rtk())

        async def check_metadata():
            try:
                metadata = await asyncio.to_thread(inspect_components)
            except Exception:
                return
            if generation == self._agent_scan_generation:
                self.component_metadata = metadata
                self._invalidate()

        tasks.append(check_metadata())
        try:
            await asyncio.gather(*tasks)
        finally:
            if generation == self._agent_scan_generation:
                self._agent_scan_completed_at = time.monotonic()

    def _make_selector(self) -> KeyboardList:
        # Display components by category without changing dependency/install order.
        names = dict(COMPONENTS)
        entries = [
            Entry(code, names[code], group, self.available[code],
                  DESCRIPTIONS.get(code, "Developer tool"))
            for group, codes in GROUPS for code in codes
        ]
        categorized = {entry.key for entry in entries}
        entries.extend(
            Entry(code, label, "OTHER", self.available[code],
                  DESCRIPTIONS.get(code, "Developer tool"))
            for code, label in COMPONENTS if code not in categorized
        )
        return KeyboardList(
            entries,
            multiple=True,
            on_enter=self.confirm_selection,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._invalidate,
            on_filter=self._begin_filter,
            on_details=self._show_component_info,
            on_refresh=self._refresh_agent_status,
            get_columns=self._component_list_width,
        )

    def _make_cleaner_list(self) -> KeyboardList:
        return KeyboardList(
            [], multiple=True, bulk_allowed=lambda entry: entry.key in SAFE_KEYS,
            on_all=self._select_all_cleaners, on_manual_selection=self._clear_cleaner_all_intent,
            on_enter=self.confirm_cleaners, on_back=self.back, on_help=self._show_help,
            on_change=self._invalidate, on_refresh=self.open_cleaner,
            on_details=self._show_cleaner_info, on_filter=self._begin_filter,
            get_columns=self._component_list_width,
        )

    def _clear_cleaner_all_intent(self) -> None:
        self.cleaner_all_requested = False

    def _select_all_cleaners(self) -> None:
        # All is a global safe preset, not a snapshot of the visible or already
        # measured rows. Manual changes cancel this intent.
        self.cleaner_all_requested = True
        self.cleaner_list.selected = {
            entry.key for entry in self.cleaner_list.entries
            if entry.selectable and entry.key in SAFE_KEYS
        }
        self._notice("All safe selected. Waiting for remaining safe checks..."
                     if self._cleaner_all_pending() else
                     "All available safe cleaners selected. Manual items excluded.")

    def _cleaner_all_pending(self) -> bool:
        return (self.cleaner_all_requested
                and self.cleaner_scan_task is not None
                and not self.cleaner_scan_task.done()
                and bool(SAFE_KEYS - self.cleaner_rows.keys()))

    def _cleaner_entries(self) -> None:
        # Stable order and cursor: never rebuild the widget as results arrive.
        entries = []
        for key, item in CLEANER_ITEMS.items():
            row = self.cleaner_rows.get(key)
            risk = "SAFE" if key in SAFE_KEYS else "MANUAL"
            status = "Checking..." if row is None else row.estimate if row.available else "Unavailable"
            entries.append(Entry(
                key, item.label, item.group, f"{risk} | {status}",
                item.description, selectable=row is not None and row.available,
            ))
        self.cleaner_list.entries = entries
        self.cleaner_list.selected.intersection_update(
            entry.key for entry in entries if entry.selectable
        )
        if self.cleaner_all_requested:
            self.cleaner_list.selected = {entry.key for entry in entries
                                          if entry.selectable and entry.key in SAFE_KEYS}
        self._invalidate()

    def _cancel_cleaner_scan(self) -> None:
        self.cleaner_scan_generation += 1
        if self.cleaner_scan_task is not None and not self.cleaner_scan_task.done():
            self.tasks.cancel("cleaner")
        self.cleaner_scan_task = None

    def open_cleaner(self) -> None:
        if self.busy:
            return
        if self.cleaner_scan_task is not None and not self.cleaner_scan_task.done():
            self._notice("Scan already running. Ready items can be selected; Esc returns home.")
            return
        self.action = "clean"
        self.dry_run = False
        self.cleaner_rows.clear()
        self.cleaner_all_requested = False
        self.cleaner_list.selected.clear()
        self.filter_active = False
        self.cleaner_list.set_query("")
        self._cleaner_entries()
        self._notice("Read-only scan started. Select ready items or press Esc.")
        self.navigate("cleaner", self.cleaner_list.window)
        self.cleaner_scan_generation += 1
        self.cleaner_scan_task = self.tasks.start("cleaner",
            self._scan_cleaners(self.cleaner_scan_generation)
        )

    async def _scan_cleaners(self, generation: int) -> None:
        limit = asyncio.Semaphore(PROBE_CONCURRENCY)

        async def check(group: str) -> None:
            try:
                async with limit:
                    rows = await probe_group(group)
            except Exception as exc:
                reason = "Scan timed out" if isinstance(exc, asyncio.TimeoutError) else str(exc)
                rows = [Scan(key, False, "-", reason) for key in PROBE_GROUPS[group]]
            if generation != self.cleaner_scan_generation:
                return
            self.cleaner_rows.update((row.key, row) for row in rows)
            self._cleaner_entries()
            if self.screen == "cleaner" and not self.filter_active:
                done = len(self.cleaner_rows)
                total = len(CLEANER_ITEMS)
                ready = sum(row.available for row in self.cleaner_rows.values())
                self._notice(f"{done}/{total} checked | {ready} ready | "
                             + ("All safe: waiting for checks" if self._cleaner_all_pending() else
                                "All safe selected" if self.cleaner_all_requested else
                                "a = All safe; r = rescan" if done == total else "Scanning remaining items..."))

        await asyncio.gather(*(check(group) for group in PROBE_GROUPS))

    def _cleaner_summary(self):
        done = len(self.cleaner_rows)
        total = len(CLEANER_ITEMS)
        ready = sum(row.available for row in self.cleaner_rows.values())
        selected = self.cleaner_list.current_values
        manual = sum(key not in SAFE_KEYS for key in selected)
        pending = len(SAFE_KEYS - self.cleaner_rows.keys()) if self._cleaner_all_pending() else 0
        width = 12
        filled = width * done // total
        return [
            ("class:running" if done < total else "class:checked",
             f"  {'Scanning' if done < total else 'Scan complete'} "
             f"[{'#' * filled}{'.' * (width - filled)}] {done}/{total}\n"),
            ("class:body", f"  Ready {ready} | Selected {len(selected)} ({manual} manual)"
             + (f" | All safe: {pending} pending" if pending else
                " | All safe selected" if self.cleaner_all_requested else " | a = All safe") + "\n"),
        ]

    def _cleaner_details(self):
        item = self.cleaner_list.current
        if item is None:
            return [("class:muted", "No cleanup item.")]
        row = self.cleaner_rows.get(item.key)
        risk = "SAFE / regenerable" if item.key in SAFE_KEYS else "MANUAL / explicit consent"
        return [
            ("class:title", item.label + "\n"),
            ("class:checked" if item.key in SAFE_KEYS else "class:warning", risk + "\n\n"),
            ("class:body", item.description + "\n\n"),
            ("class:running" if row is None else "class:body",
             "Checking availability and size..." if row is None else
             (f"{'Engine category estimate' if item.key.startswith('docker-') else 'Cache estimate'}: {row.estimate}\n" if row.available else "Unavailable\n") + row.note),
        ]

    def _show_cleaner_info(self) -> None:
        self.info_view.text = "".join(text for _, text in self._cleaner_details())
        self.navigate("cleaner_info", self.info_view)

    def confirm_cleaners(self) -> None:
        if self.busy:
            return
        if self._cleaner_all_pending():
            self._notice("All safe: waiting for remaining safe checks before confirmation. Esc returns home.")
            return
        self.selected = self.cleaner_list.current_values
        if not self.selected:
            self._notice("Select a ready cleaner using Space or a (All safe).")
            return
        self.auto_added = []
        self._make_confirmation()

    def _make_options(self, entries: list[Entry]) -> KeyboardList:
        return KeyboardList(
            entries,
            multiple=True,
            bulk_select=False,  # Never bulk-consent to root group/key changes.
            empty_text="No optional changes required.",
            on_enter=self.execute_selection,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._refresh_confirm_plan,
            on_dry=self.toggle_dry_run,
            get_columns=self.columns,
        )

    def _make_log_list(self, paths: list[Path]) -> KeyboardList:
        entries = []
        for path in paths:
            parts = path.stem.split("-", 3)
            if len(parts) >= 3 and len(parts[0]) == 8 and len(parts[1]) == 6:
                date = parts[0]
                hour = parts[1]
                title = (f"{parts[2].title():<12} "
                         f"{date[:4]}-{date[4:6]}-{date[6:]} "
                         f"{hour[:2]}:{hour[2:4]} UTC")
            else:
                title = path.name
            report = self.history_reports.get(path)
            entries.append(Entry(str(path), title, status=report.heading if report else "",
                                 description=str(path)))
        return KeyboardList(
            entries,
            empty_text="No saved logs found.",
            on_enter=self.open_history,
            on_back=self.back,
            on_help=self._show_help,
            on_change=self._invalidate,
            on_filter=self._begin_filter,
            get_columns=self.columns,
        )

    def _invalidate(self) -> None:
        if hasattr(self, "app"):
            self.app.invalidate()

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

    def _component_details(self, *, full: bool = False):
        item = self.selector.current
        if item is None:
            return [("class:muted", "  No matching component")]

        deps = ", ".join(DEPENDENCIES.get(item.key, ())) or "None"
        selected = item.key in self.selector.selected
        status_style = STATUS_STYLES.get(item.status, "class:body")
        if self.columns() < 94 and not full:
            # The medium stacked preview has just six lines of vertical space.
            out = [
                ("class:title", f"  {item.label}\n"),
                ("class:body", f"  {item.description}\n"),
                ("class:muted", "  State: "),
                (status_style, item.status + "\n"),
                ("class:muted", "  Requires: "),
                ("class:body", deps + "\n"),
                ("class:muted", "  Selected: "),
                ("class:body", ("Yes" if selected else "No") + "\n"),
            ]
            if item.key == "ponytail":
                out.append(("class:muted", "  Press i for each agent's plugin status\n"))
            elif item.key in WARNINGS:
                out.append(("class:warning", "  NOTE: " + WARNINGS[item.key]))
            return out

        installed_count = sum(v == "Installed" for v in self.available.values())
        missing_count = sum(v == "Missing" for v in self.available.values())
        unverified_count = sum(v == "Unverified" for v in self.available.values())
        other_count = len(self.available) - installed_count - missing_count - unverified_count
        selected_count = len(self.selector.selected)
        out = [
            ("class:section", "  COMPONENT DETAILS\n\n"),
            ("class:title", "  " + item.label + "\n"),
            ("class:muted", "  " + (item.group or "OTHER") + "\n\n"),
        ]
        # Put per-agent information *first*, where it is visible without
        # scrolling even on moderately tall terminal windows.
        if item.key == "ponytail":
            out.append(("class:section", "  AGENT INTEGRATIONS\n"))
            for agent in AGENTS:
                state = self.ponytail_agents.get(agent, "Unavailable")
                out.extend([
                    ("class:muted", f"  {LABELS[agent]:<12} "),
                    (STATUS_STYLES.get(state, "class:body"), state + "\n"),
                ])
                detail = self.ponytail_details.get(agent)
                if detail:
                    out.append(("class:muted", f"    {detail.source}: {detail.reason}\n"))
            out.append(("class:muted", "  r to refresh · registration, not runtime activation\n\n"))
        out.extend([
            ("class:section", "  OVERVIEW\n"),
            ("class:muted", "  State: "),
            (status_style, item.status + "\n"),
            ("class:muted", "  Selected: "),
            ("class:body", ("Yes" if selected else "No") + "\n"),
            ("class:muted", "  Requires: "),
            ("class:body", deps + "\n\n"),
            ("class:section", "  DESCRIPTION\n"),
            ("class:body", "  " + item.description + "\n\n"),
            ("class:section", "  INVENTORY\n"),
            ("class:body", f"  {installed_count} installed  ·  {missing_count} missing\n"),
        ])
        if unverified_count or other_count:
            out.append(("class:warning", f"  {unverified_count} unverified  ·  {other_count} other\n"))
        out.append(("class:muted", f"  {selected_count} / {len(self.selector.entries)} selected\n"))
        metadata = self.component_metadata.get(item.key)
        if metadata:
            out.extend([("class:section", "\n  INSTALLATION\n"),
                        ("class:body", "  " + metadata + "\n")])
        if item.key in WARNINGS:
            out.extend([
                ("class:section", "\n  NOTE\n"),
                ("class:warning", "  " + WARNINGS[item.key] + "\n"),
            ])
        out.extend([
            ("class:section", "\n  QUICK ACTIONS\n"),
            ("class:muted", "  Space  Select / deselect\n"),
            ("class:muted", "  /      Filter components\n"),
            ("class:muted", "  r      Refresh inventory\n"),
            ("class:muted", "  Enter  Continue\n"),
        ])
        return out

    def _progress_tokens(self):
        active = [code for code, state in self.status.items() if state != "--"]
        complete = [
            code for code in active if self.status[code] in FINAL_STATES
        ]
        running = [
            code for code in active if self.status[code] == "RUNNING"
        ]
        current = running[0] if running else self.current_action
        elapsed = f" · {time.monotonic() - self.run_started:.1f}s" if self.run_started is not None else ""
        if not active:
            return [
                ("class:running", "  " + self.current_action.upper() + "\n"),
                ("class:muted", "  Running system command..." + elapsed),
            ]
        return [
            ("class:running", f"  {self.current_action.upper()} "),
            ("class:muted", f" {len(complete)} / {len(active)} complete\n"),
            ("class:body", "  Current: " + current + elapsed),
        ]

    def _history_details(self):
        item = self.log_files.current
        if item is None:
            return [("class:muted", "  No logs found.")]
        path = Path(item.key)
        try:
            stat = path.stat()
            size, mtime_ns = stat.st_size, stat.st_mtime_ns
        except OSError:
            size, mtime_ns = 0, 0
        report = self.history_reports.get(path)
        summary = (f"  {report.heading} | {report.duration:.1f}s\n  {summarize_status(report.status)}\n" if report else "  Legacy log (no structured report)\n")
        return [
            ("class:section", "  SELECTED RUN\n\n"),
            ("class:body", summary),
            ("class:title", "  " + item.label + "\n\n"),
            ("class:muted", f"  Size: {size:,} bytes\n"),
            ("class:muted", "  " + str(path) + "\n\n"),
            ("class:section", "  LAST OUTPUT\n"),
            ("class:body", "  " + _cached_log_tail(
                str(path), size, mtime_ns
            ).replace("\n", "\n  ")),
        ]

    def _show_component_info(self) -> None:
        self.info_view.text = "".join(text for _style, text in self._component_details(full=True))
        self.navigate("info", self.info_view)

    def _begin_filter(self) -> None:
        self.filter_active = True
        self.filter_input.text = ""
        self.app.layout.focus(self.filter_input)
        self._notice("Filter by name or description. Enter to return to the list.")
        self._invalidate()

    def _active_list(self) -> KeyboardList:
        if self.screen == "logs":
            return self.log_files
        if self.screen == "cleaner":
            return self.cleaner_list
        return self.selector

    def _filter_changed(self, _buffer) -> None:
        self._active_list().set_query(self.filter_input.text)

    def _finish_filter(self) -> bool:
        self.filter_active = False
        active = self._active_list()
        self.app.layout.focus(active.window)
        if active.query:
            self._notice(
                f"Filter: {active.query!r} ({len(active.visible)} results). "
                "Esc clears filter; / edits."
            )
        else:
            self._notice("Filter cleared. Esc returns to the main menu.")
        return True

    def _cancel_filter(self) -> None:
        self.filter_input.text = ""
        self._active_list().set_query("")
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

        if widget is self.confirm_plan:
            @kb.add("enter")
            def _confirm(_event):
                self.execute_selection()

            @kb.add("d")
            def _dry(_event):
                self.toggle_dry_run()

        if widget is self.status_view:
            @kb.add("l")
            def _expand(_event):
                self.expanded_log = not self.expanded_log
                self.status_view.window.height = (
                    Dimension(min=3, max=4) if self.expanded_log
                    else Dimension(weight=3, min=6)
                )
                self.log_view.window.height = (
                    Dimension(weight=1, min=6) if self.expanded_log
                    else Dimension(weight=2, min=5)
                )
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

        @kb.add("y", filter=Condition(lambda: self.screen == "update_prompt"), eager=True)
        @kb.add("Y", filter=Condition(lambda: self.screen == "update_prompt"), eager=True)
        def _yes_update(_event):
            self._answer_update(True)

        @kb.add("n", filter=Condition(lambda: self.screen == "update_prompt"), eager=True)
        @kb.add("N", filter=Condition(lambda: self.screen == "update_prompt"), eager=True)
        def _no_update(_event):
            self._answer_update(False)

        @kb.add("tab", filter=Condition(lambda: self.screen == "confirm" and bool(self.options.entries)), eager=True)
        def _switch_confirm_focus(_event):
            if self.app.layout.has_focus(self.options.window):
                self.app.layout.focus(self.confirm_plan)
            else:
                self.app.layout.focus(self.options.window)

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
        if screen == "home" and self.pending_update is not None and not self.busy:
            self._show_update_prompt()

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
            self.available = inventory(self.ponytail_agents, quick=True)
            self.dry_run = False
            # Preserve last inventory while navigating; refresh lazily after TTL.
            self.selector = self._make_selector()
            self._layout_cache.pop("select-wide", None)
            self._layout_cache.pop("select-medium", None)
            self.filter_active = False
            self.filter_input.text = ""
            self._notice(f"Select tools to {action}. Space toggles the highlighted row.")
            self.navigate("select", self.selector.window)
            self._schedule_agent_scan()
        elif action == "clean":
            self.open_cleaner()
        elif action == "logs":
            self.list_history()
        elif action == "update":
            self.update_revision = ""
            self.action = action
            self.dry_run = False
            self.selected = []
            self.auto_added = []
            self._make_confirmation()
        elif action is not None:
            self.dry_run = False
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
        if self.action == "clean" and any(k not in SAFE_KEYS for k in self.selected):
            options.append(Entry("risk", "I accept permanent loss of manually selected resources", "CONSENT"))
            for key in self.selected:
                row = self.cleaner_rows.get(key)
                if key not in {"docker-unused-images", "docker-volumes"} or row is None:
                    continue
                for resource in row.resources:
                    options.append(Entry(resource["token"], resource["label"],
                                         CLEANER_ITEMS[key].label, resource["size"]))
        if self.action == "install":
            if "zsh" in self.selected:
                options.append(Entry("change_shell", "Set Zsh as login shell"))
            if "docker" in self.selected:
                options.append(Entry("docker_group", "Join docker group (root-equivalent)"))
            if "keychain" in self.selected:
                options.append(Entry("ssh_key", "Generate unencrypted Ed25519 key if needed"))
            if {"rtk", "ponytail"} & set(self.selected):
                for agent, label, binary in AGENT_EXECUTABLES:
                    if shutil.which(binary):
                        options.append(Entry("agent_" + agent, "Integrate with " + label))
        self.options = self._make_options(options)
        self._layout_cache.pop("confirm", None)
        self._refresh_confirm_plan()
        if self.action == "update":
            self._notice("Review the plan. Enter updates Devbox.")
        elif self.dry_run:
            self._notice("Dry-run ON. Enter previews only; d enables changes.")
        elif self.action == "clean" and self.options.entries:
            self._notice("Manual items require consent. Space acknowledges; Enter confirms.")
        else:
            self._notice("Review the plan. Enter applies changes; d previews only.")
        self.navigate("confirm", self._confirm_focus())

    def _chosen_agents(self) -> list[str]:
        if not hasattr(self, "options") or self.action != "install":
            return []
        selected = set(self.options.current_values)
        return [agent for agent, _, _ in AGENT_EXECUTABLES if "agent_" + agent in selected]

    def _selection_summary(self) -> str:
        if self.action == "update":
            return "Update Devbox source\n\nFast-forward only.\nDevbox exits after success; run devbox again to load the new version."
        mode = "DRY RUN (no changes)" if self.dry_run else "Apply selected changes"
        if self.action == "clean":
            lines = [f"Clean: {len(self.selected)} item(s)", mode, ""]
            for key in self.selected:
                item = CLEANER_ITEMS[key]
                row = self.cleaner_rows.get(key)
                estimate = row.estimate if row and row.available else "unknown"
                risk = "SAFE" if key in SAFE_KEYS else "MANUAL"
                lines.append(f"  {risk:6}  {item.label} — {estimate}")
                if not item.safe:
                    lines.append("          " + item.description)
            if self.cleaner_all_requested:
                excluded = [row for key, row in self.cleaner_rows.items()
                            if key in SAFE_KEYS and not row.available]
                if excluded:
                    lines += ["", "Unavailable safe cleaners (not selected):"]
                    lines += [f"  {CLEANER_ITEMS[row.key].label}: {row.note}" for row in excluded]
            lines += ["", "Estimates may overlap; eligibility is rechecked at execution."]
            if any(CLEANER_ITEMS[k].sudo for k in self.selected):
                lines.append("Sudo authentication required for selected APT cleanup.")
            if any(k not in SAFE_KEYS for k in self.selected):
                lines.append("Manual items require explicit consent before deletion.")
            if any(k in {"docker-unused-images", "docker-volumes"} for k in self.selected):
                lines.append("Select exact image IDs/volume names in Options; no bulk prune.")
                chosen_resources = [key for key in self.options.current_values if key.startswith(("image:", "volume:"))]
                lines.append(f"Individual resources selected: {len(chosen_resources)}")
                lines.extend("  " + entry.label for entry in self.options.entries
                             if entry.key in chosen_resources)
            return "\n".join(lines)
        labels = dict(COMPONENTS)
        lines = [f"{self.action.title()}: {len(self.selected)} component(s)", mode, ""]
        for code in self.selected:
            lines.append("  " + labels.get(code, code) +
                         (" (dependency)" if code in self.auto_added else ""))
        if "nvidia" in self.selected:
            lines += ["", "Warning: NVIDIA setup may restart Docker."]
        if "docker" in self.selected and self.action == "upgrade":
            lines += ["", "Warning: Docker upgrade may restart containers."]
        agents = self._chosen_agents()
        if agents:
            lines += ["", "Agent targets: " + ", ".join(agents)]
        elif "ponytail" in self.selected and self.action == "install":
            lines += ["", "Select an agent target for Ponytail (required)."]
        return "\n".join(lines)

    def toggle_dry_run(self) -> None:
        if self.action == "update":
            self._notice("Devbox source update cannot be dry-run in the TUI.")
            return
        if self.busy:
            self._notice("Cannot change preview while a task is active.")
            return
        self.dry_run = not self.dry_run
        self._refresh_confirm_plan()
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
            endpoints = {self.cleaner_rows[key].endpoint for key in chosen
                         if action == "clean" and key in self.cleaner_rows and self.cleaner_rows[key].endpoint}
            if len(endpoints) > 1:
                raise ValueError("Docker context changed during scan; rescan required.")
            command = build_command(action, chosen, dry_run=self.dry_run,
                                    agents=self._chosen_agents() if action == "install" else [],
                                    allow_risky=action == "clean" and "risk" in self.options.current_values,
                                    resources=[key for key in self.options.current_values if key.startswith(("image:", "volume:"))] if action == "clean" else [],
                                    docker_endpoint=next(iter(endpoints), ""),
                                    update_revision=self.update_revision if action == "update" else "")
        except ValueError as exc:
            self._notice(str(exc))
            return

        # Stop read-only workers before executing any mutating job.
        self._cancel_cleaner_scan()
        self._invalidate_agent_scan()
        if action == "update":
            self._cancel_update_check()
        # Reserve the slot before creating a task: rapid Enter cannot overlap APT.
        self.busy = True
        self.current_action = action.title() + (" (dry-run)" if self.dry_run and action in ("install", "upgrade", "clean") else "")
        self.run_report = None
        self.outcome_details = {}
        self.status = {code: ("QUEUED" if code in chosen else "--")
                       for code in (CLEANER_ITEMS if action == "clean" else ORDER)}
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
            self._notice("sudo is unavailable. Selected operation requires sudo.")
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
        started = time.monotonic()
        self.run_started = started
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            # User-scoped AI extensions never need the preflight sudo prompt.
            needs_sudo = any(code not in {"rtk", "skills-cli", "ponytail"} for code in selected)
            if action == "clean":
                needs_sudo = any(CLEANER_ITEMS[key].sudo for key in selected)
            if action in ("install", "upgrade", "clean") and needs_sudo and not self.dry_run:
                if not await self._authorize_sudo():
                    code = 1
                    self.last_result = "Cannot start: sudo authentication not completed."
                    return
                keepalive = asyncio.create_task(self._sudo_keepalive())

            files = prepare_run(STATE_ROOT, action)
            self.log_path, self.event_path = files.log, files.events
            enabled = set(self.options.current_values) if action == "install" else set()
            with os.fdopen(files.fd, "wb", buffering=0) as output:
                self.process = await launch(command, root=ROOT, env=run_env(files.events, enabled), output=output)
                self._notice(f"{action.title()} running. Log: {self.log_path}")
                code = await wait_for_run(self.process, self._refresh)
            self._refresh()
            self.last_result = (("Preview complete — no changes made." if self.dry_run and action in ("install", "upgrade", "clean")
                                 else "Completed successfully.") if code == 0
                                else f"Failed with exit code {code}.")
            if action == "update" and code == 0:
                self.last_result = "Devbox updated successfully. Run devbox again to load the new version."
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
            for component in selected:
                if self.status.get(component) in ("RUNNING", "QUEUED"):
                    self.status[component] = ("FAILED" if code != 0 and self.status[component] == "RUNNING" else "NOT_RUN")
            self.run_report = RunReport(action, timestamp, round(time.monotonic() - started, 2),
                                        code, self.dry_run, {k: v for k, v in self.status.items() if v != "--"},
                                        dict(self.outcome_details), self.last_result)
            if self.log_path is not None:
                try:
                    write_report(self.log_path, self.run_report)
                except OSError as exc:
                    self.last_result += f" (report not saved: {exc})"
            # Changes to agent plugins can occur during install; invalidate the
            # cached report for the next Components screen, without blocking Result.
            self._invalidate_agent_scan()
            self._render_result()
            self._notice(self.last_result)
            if action == "update" and code == 0 and self.app.is_running:
                self.exit_message = self.last_result
                if self.log_path is not None:
                    self.exit_message += f"\nUpdate log: {self.log_path}"
                self.app.exit()
            else:
                self.navigate("result", self.results_view)

    def _render_status(self) -> str:
        labels = dict(COMPONENTS) | {key: item.label for key, item in CLEANER_ITEMS.items()}
        return status_lines(self.current_action, self.status, labels, self.outcome_details)

    def _refresh(self) -> None:
        events, details, self.event_offset = read_run_events(self.event_path, self.event_offset)
        for name, state in events:
            if name in self.status and (state in FINAL_STATES or state == "RUNNING"):
                self.status[name] = state
        self.outcome_details.update((name, detail) for name, detail in details if name in self.status)
        status_text = self._render_status()
        log_text = log_tail(
            self.log_path, count=25 if self.expanded_log else 10
        )
        # Rewriting a TextArea buffer on every 300ms poll resets selection
        # and scroll position, even when there is no new event or log text.
        changed = False
        if self.status_view.text != status_text:
            self.status_view.text = status_text
            changed = True
        if self.log_view.text != log_text:
            self.log_view.text = log_text
            changed = True
        if changed:
            self._invalidate()

    def _render_result(self) -> None:
        report = self.run_report
        heading = report.heading if report else ("SUCCESS" if self.last_code == 0 else "FAILED")
        lines = [f"  {heading} — {self.current_action}: {self.last_result}", ""]
        if report:
            lines.extend([f"  Duration: {report.duration:.1f}s | {summarize_status(report.status)}", ""])
        lines.extend([self._render_status(), "", f"  Full log: {self.log_path or '(not created)'}",
                      "", "  LAST OUTPUT", log_tail(self.log_path, count=22)])
        self.results_view.text = "\n".join(lines)

    def list_history(self) -> None:
        log_dir = STATE_ROOT / "logs"
        paths = sorted(log_dir.glob("*.log"), reverse=True)[:100] if log_dir.exists() else []
        self.history_reports = {path: read_report(path) for path in paths}
        self.log_files = self._make_log_list(paths)
        self._layout_cache.pop("logs-wide", None)
        self.filter_active = False
        self.filter_input.text = ""
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
        elif self.screen == "update_prompt":
            self._decline_update()
        elif self.screen == "confirm":
            if self.action == "clean":
                self.navigate("cleaner", self.cleaner_list.window)
            elif self.action == "update":
                self.navigate("home", self.menu.window)
            else:
                self.navigate("select", self.selector.window)
        elif self.screen == "cleaner_info":
            self.navigate("cleaner", self.cleaner_list.window)
        elif self.screen == "info":
            self.navigate("select", self.selector.window)
        elif self.screen in ("select", "logs", "cleaner") and self.filter_active:
            self._cancel_filter()
        elif self.screen in ("select", "logs", "cleaner") and self._active_list().query:
            self.filter_input.text = ""
            self._active_list().set_query("")
            self._notice("Filter cleared. Press Esc again to return.")
        elif self.screen in ("select", "result", "logs", "cleaner"):
            if self.screen == "cleaner":
                self._cancel_cleaner_scan()
                self._notice("Returned home. Open Cleaner to scan again.")
            self.navigate("home", self.menu.window)

    def _focus_for(self, screen: str):
        return {
            "home": self.menu.window, "select": self.selector.window,
            "update_prompt": self.update_choices.window,
            "cleaner": self.cleaner_list.window,
            "confirm": self._confirm_focus(), "result": self.results_view,
            "logs": self.log_files.window, "view_log": self.history_view,
            "run": self.status_view, "info": self.info_view, "cleaner_info": self.info_view,
        }.get(screen, self.help_view)

    def quit(self) -> None:
        if self.busy:
            self._notice("Finish the running task before exiting.")
            return
        self._cancel_cleaner_scan()
        self._cancel_update_check()
        self._invalidate_agent_scan()
        self.tasks.cancel_all()
        self.app.exit()

    def run(self) -> None:
        async def session():
            try:
                await self.app.run_async(pre_run=self._start_update_check)
            finally:
                await self.tasks.close()
        asyncio.run(session())
        if self.exit_message:
            print(self.exit_message)


def main() -> None:
    DevboxTUI().run()


if __name__ == "__main__":
    main()
