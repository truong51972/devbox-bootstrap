"""Toolkit screen controller, separate from bootstrap and Cleaner controllers."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shlex
import shutil

from prompt_toolkit.application import in_terminal
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, DynamicContainer
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea

from tui.ui import Entry, KeyboardList
from tui.views import WIDE_LAYOUT_MIN, detail_panel_width
from .registry import ACTIONS, BY_ID, execute
from .operations import prepare, apply
from .settings import favorites, toggle_favorite
from .workflows import list_workflows
from .native import safe_text

MANAGED = {
    "sys.terminate": ("Terminate process", "System", "Send SIGTERM to a verified user-owned PID.", "PID"),
    "docker.start": ("Start container", "Containers", "Start an exact local Docker container.", "Container name or ID"),
    "docker.stop": ("Stop container", "Containers", "Stop an exact local Docker container.", "Container name or ID"),
    "docker.restart": ("Restart container", "Containers", "Restart an exact local Docker container.", "Container name or ID"),
}


class ToolkitScreens:
    def init_toolkit(self):
        self.toolkit_cwd = os.environ.get("DEVBOX_INVOCATION_CWD") or str(Path.cwd())
        self.toolkit_category = None
        self.toolkit_key = ""
        self.toolkit_task = None
        self.toolkit_plan = None
        self.toolkit_workflow = None
        self.toolkit_workflows = {}
        self.toolkit_favorites = set(favorites())
        self.toolkit_recent = []
        self.toolkit_list = KeyboardList([], on_enter=self.toolkit_open_action,
            on_back=self.back, on_help=self._show_help, on_change=self._invalidate,
            on_filter=self._begin_filter, on_details=self.toolkit_favorite,
            get_columns=self._component_list_width)
        self.toolkit_input = TextArea(multiline=True, scrollbar=True, wrap_lines=True)
        self.toolkit_result = TextArea(read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.toolkit_confirm = KeyboardList(
            [Entry("no", "No — go back"), Entry("yes", "Yes — execute this action")],
            on_enter=self.toolkit_confirm_action, on_back=self.back,
            on_help=self._show_help, on_change=self._invalidate, get_columns=self.columns)
        keys = KeyBindings()
        @keys.add("c-s", eager=True)
        def _submit(_event):
            self.toolkit_submit()
        @keys.add("escape", eager=True)
        def _back(_event):
            self.back()
        self.toolkit_input.control.key_bindings = keys
        result_keys = KeyBindings()
        @result_keys.add("escape")
        @result_keys.add("enter")
        def _close(_event):
            self.back()
        @result_keys.add("r")
        def _repeat(_event):
            if not self.busy and not self.toolkit_running():
                self.toolkit_open_action()
        self.toolkit_result.control.key_bindings = result_keys

    def build_toolkit_views(self):
        self.views["toolkit"] = self._page("Quick actions", HSplit([
            DynamicContainer(self.toolkit_layout), DynamicContainer(self._filter_layout),
        ]), "↑↓ Move   / Search   i Favorite   Enter Open   Esc Back")
        self.views["toolkit_input"] = self._page("Action input", HSplit([
            self._text(self.toolkit_prompt, height=3), self._divider(), self.toolkit_input,
        ]), "Ctrl+S Run   Enter New line   Esc Back")
        self.views["toolkit_result"] = self._page("Action result", self.toolkit_result,
            "↑↓ Scroll   r Repeat   Enter/Esc Back")
        self.views["toolkit_confirm"] = self._page("Confirm action", HSplit([
            self._text(self.toolkit_confirmation, height=6), self._divider(), self.toolkit_confirm.window,
        ]), "↑↓ Choose   Enter Confirm   Esc Back")

    def toolkit_running(self):
        return self.toolkit_task is not None and not self.toolkit_task.done()

    def toolkit_entries(self):
        rows = []
        for a in ACTIONS:
            if self.toolkit_category not in (None, "Favorites", a.category):
                continue
            if self.toolkit_category == "Favorites" and a.id not in self.toolkit_favorites:
                continue
            rows.append(Entry(a.id, a.label, a.category, "★" if a.id in self.toolkit_favorites else "",
                              a.description + " " + a.id))
        for key, (label, category, description, _) in MANAGED.items():
            if self.toolkit_category in (None, category):
                rows.append(Entry(key, label, category, "", description + " " + key))
        for key, w in self.toolkit_workflows.items():
            if self.toolkit_category in (None, "Workflows"):
                rows.append(Entry("run:" + key, key, "Workflows", "", w.description))
        if self.toolkit_category is None:
            order = {key: index for index, key in enumerate(self.toolkit_recent)}
            rows.sort(key=lambda r: (r.group, r.key not in self.toolkit_favorites, order.get(r.key, 999), r.label))
        else:
            rows.sort(key=lambda r: (r.group, r.label))
        return rows

    def open_toolkit(self, category=None):
        if self.busy:
            return
        self.toolkit_category = category
        try:
            self.toolkit_workflows = list_workflows()
        except (ValueError, OSError) as exc:
            self.toolkit_workflows = {}
            self._notice("Invalid workflows file: " + str(exc), style="class:warning")
        else:
            self._notice((category or "All actions") + " · Search by label or action ID.")
        self.toolkit_list.entries = self.toolkit_entries()
        self.toolkit_list.set_query("")
        self.filter_active = False
        self.navigate("toolkit", self.toolkit_list.window)

    def toolkit_layout(self):
        if self.columns() >= WIDE_LAYOUT_MIN:
            return self._layout("toolkit-wide", lambda: VSplit([
                self.toolkit_list.window, self._divider_v(),
                self._text(self.toolkit_details, width=lambda: Dimension.exact(detail_panel_width(self.columns()))),
            ], padding=1))
        if self.rows() >= 25 and self.columns() >= 64:
            return self._layout("toolkit-medium", lambda: HSplit([
                self.toolkit_list.window, self._divider(), self._text(self.toolkit_details, height=6),
            ]))
        return self.toolkit_list.window

    def toolkit_details(self):
        entry = self.toolkit_list.current
        if entry is None:
            return [("class:muted", "  No matching action.")]
        action = BY_ID.get(entry.key)
        mode = action.mode if action else "explicit confirmation"
        return [("class:section", "  " + (self.toolkit_category or "ALL ACTIONS").upper() + "\n\n"),
                ("class:title", "  " + entry.label + "\n\n"),
                ("class:body", "  " + entry.description + "\n\n"),
                ("class:muted", "  Mode: " + mode + "\n"),
                ("class:muted", "  Project: " + self.toolkit_cwd + "\n"),
                ("class:muted", "  i Favorite · / Search\n")]

    def toolkit_favorite(self):
        key = self.toolkit_list.current_value
        if key not in BY_ID:
            self._notice("Only registered read-only utilities can be favorited.")
            return
        try:
            enabled = toggle_favorite(key)
        except (ValueError, OSError) as exc:
            self._notice("Could not save favorite: " + str(exc), style="class:error")
            return
        if enabled:
            self.toolkit_favorites.add(key)
        else:
            self.toolkit_favorites.discard(key)
        self.toolkit_list.entries = self.toolkit_entries()
        self._notice("Favorite saved." if enabled else "Favorite removed.")

    def toolkit_prompt(self):
        action = BY_ID.get(self.toolkit_key)
        label = action.prompt if action else MANAGED.get(self.toolkit_key, ("", "", "", "Input"))[3]
        return [("class:title", "  " + label + "\n"),
                ("class:muted", "  Ctrl+S submits. Input is not written to history.\n")]

    def toolkit_confirmation(self):
        if self.toolkit_plan is not None:
            desc = self.toolkit_plan.description
        elif self.toolkit_workflow is not None:
            desc = "Launch: " + shlex.join(self.toolkit_workflow.command)
        else:
            desc = "No action pending."
        return [("class:warning", "  EXPLICIT CONFIRMATION\n\n"), ("class:body", "  " + safe_text(desc) + "\n"),
                ("class:muted", "  Working directory: " + self.toolkit_cwd + "\n")]

    def toolkit_open_action(self):
        if self.toolkit_running():
            self._notice("A query is still running; wait for it to complete.")
            return
        key = self.toolkit_list.current_value
        if not key:
            return
        self.toolkit_key = key
        self.toolkit_plan = None
        self.toolkit_workflow = None
        self.toolkit_input.text = ""
        if key.startswith("run:"):
            self.toolkit_workflow = self.toolkit_workflows[key[4:]]
            self.toolkit_confirm.index = 0
            self.navigate("toolkit_confirm", self.toolkit_confirm.window)
        elif key in MANAGED or BY_ID[key].prompt:
            self.navigate("toolkit_input", self.toolkit_input)
        else:
            self.toolkit_submit()

    def toolkit_submit(self):
        if self.toolkit_running() or self.busy:
            return
        key = self.toolkit_key
        value = self.toolkit_input.text
        self.toolkit_input.text = ""
        if not key:
            return
        self.toolkit_result.text = "Checking…" if key in MANAGED else "Running…"
        self.navigate("toolkit_result", self.toolkit_result)
        self.toolkit_task = asyncio.create_task(self.toolkit_query(key, value))

    async def toolkit_query(self, key, value):
        try:
            if key in MANAGED:
                self.toolkit_plan = await asyncio.to_thread(prepare, key, value.strip(), self.toolkit_cwd)
                if self.screen == "toolkit_result":
                    self.toolkit_confirm.index = 0
                    self.navigate("toolkit_confirm", self.toolkit_confirm.window)
                else:
                    self.toolkit_plan = None
                return
            result = await asyncio.to_thread(execute, key, value, self.toolkit_cwd)
            if self.screen == "toolkit_result":
                self.toolkit_result.text = safe_text(result)
                self._notice("Completed. Output is not persisted.", style="class:installed")
            self.toolkit_recent = [key] + [x for x in self.toolkit_recent if x != key][:9]
        except Exception as exc:
            action = BY_ID.get(key)
            if self.screen == "toolkit_result":
                self.toolkit_result.text = "Action failed: " + ("Invalid input or query failed." if action and action.sensitive else safe_text(str(exc)))
                self._notice("Action failed.", style="class:error")

    def toolkit_confirm_action(self):
        if self.toolkit_confirm.current_value != "yes":
            self.back()
            return
        if self.busy or self.toolkit_running():
            return
        plan, workflow = self.toolkit_plan, self.toolkit_workflow
        if plan is None and workflow is None:
            return
        self.toolkit_plan = None
        self.toolkit_workflow = None
        self.busy = True
        self.toolkit_result.text = "Running confirmed action…"
        self.navigate("toolkit_result", self.toolkit_result)
        self.toolkit_task = asyncio.create_task(self.toolkit_apply(plan, workflow))

    async def toolkit_apply(self, plan, workflow):
        try:
            if workflow:
                executable = shutil.which(workflow.command[0])
                if not executable:
                    raise ValueError("Required executable unavailable.")
                async with in_terminal():
                    proc = await asyncio.create_subprocess_exec(executable, *workflow.command[1:], cwd=self.toolkit_cwd)
                    code = await proc.wait()
                if code:
                    raise ValueError(f"Workflow exited {code}.")
                result = "Workflow completed."
            else:
                result = await asyncio.to_thread(apply, plan, self.toolkit_cwd)
            self.toolkit_result.text = safe_text(result)
            self._notice("Completed.", style="class:installed")
        except Exception as exc:
            self.toolkit_result.text = "Action failed: " + safe_text(str(exc))
            self._notice("Action failed.", style="class:error")
        finally:
            self.busy = False
            self._invalidate()

    def toolkit_back(self):
        if self.screen == "toolkit":
            if self.filter_active:
                self._cancel_filter()
            elif self.toolkit_list.query:
                self.toolkit_list.set_query("")
                self._notice("Filter cleared. Esc returns home.")
            else:
                self.navigate("home", self.menu.window)
        else:
            self.toolkit_input.text = ""
            self.toolkit_result.text = ""
            self.toolkit_plan = None
            self.toolkit_workflow = None
            self.navigate("toolkit", self.toolkit_list.window)
