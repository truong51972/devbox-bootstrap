"""Shared direct-entry management screens for tools and agents."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import shlex
import time

from prompt_toolkit.application import in_terminal
from prompt_toolkit.layout import HSplit, VSplit, DynamicContainer
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea

from tui.backend import ROOT
from tui.ui import Entry, KeyboardList, status_style
from tui.views import WIDE_LAYOUT_MIN, detail_panel_width
from . import resources
from .native import safe_text


class ResourceScreens:
    def init_resources(self):
        self.resource_scope = "development"
        self.resource_rows = ()
        self.resource_cache = {}
        self.resource_task = None
        self.resource_generation = 0
        self.resource_scan_scope = None
        self.resource_operations = ()
        self.resource_advanced_parent = False
        self.resource_list = KeyboardList([], multiple=True, on_enter=self.resource_review,
            on_back=self.back, on_help=self._show_help, on_change=self._invalidate,
            on_filter=self._begin_filter, on_all=self.resource_defaults,
            on_update=self.resource_updates, on_refresh=lambda: self.resource_refresh(force=True),
            on_details=self.resource_show_details, on_edit=self.resource_advanced,
            get_columns=self._component_list_width)
        self.resource_detail = TextArea(read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.resource_plan_text = TextArea(read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.resource_result = TextArea(read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        for field in (self.resource_detail, self.resource_plan_text, self.resource_result):
            self._bind_text(field)
        self.resource_confirm = KeyboardList([
            Entry("no", "Back — no changes"), Entry("preview", "Dry run — show commands"),
            Entry("yes", "Execute reviewed operations"),
        ], on_enter=self.resource_confirm_action, on_back=self.back, on_help=self._show_help,
            on_change=self._invalidate, get_columns=self.columns)

    def resource_title(self):
        return "AI Agents" if self.resource_scope == "ai" else "Development Tools"

    def build_resource_views(self):
        self.views["resources"] = self._page(self.resource_title, HSplit([
            self._text(self.resource_summary, height=3), self._divider(),
            DynamicContainer(self.resource_layout), DynamicContainer(self._filter_layout),
        ]), "↑↓ Move  Space Select  a Missing  u Updates  n Clear  r Refresh  / Filter  i Details  e Advanced  Enter Review  Esc")
        self.views["resource_detail"] = self._page("Resource details", self.resource_detail, "↑↓ Scroll  Esc Back")
        self.views["resource_confirm"] = self._page("Review changes", HSplit([
            self.resource_plan_text, self._divider(), self.resource_confirm.window,
        ]), "↑↓ Choose  Enter Confirm  Tab Scroll plan  Esc Back")
        self.views["resource_result"] = self._page("Resource operation result", self.resource_result, "↑↓ Scroll  Esc Back")

    def resource_open(self, scope):
        if self.busy:
            return
        self.resource_scope = scope
        self.resource_advanced_parent = False
        self.resource_list.current_values = []
        self.resource_list.set_query("")
        self.filter_active = False
        cached = self.resource_cache.get(scope)
        self.resource_rows = cached[1] if cached else resources.local_rows(scope)
        self.resource_render_rows()
        self.navigate("resources", self.resource_list.window)
        self.resource_refresh()

    def resource_render_rows(self):
        key = self.resource_list.current_value
        self.resource_list.entries = [Entry(r.key, r.name, r.group, r.status,
            " ".join((r.description, r.status, r.manager, r.evidence)), selectable=bool(r.action))
            for r in self.resource_rows]
        self.resource_list.index = next((i for i, e in enumerate(self.resource_list.visible) if e.key == key),
                                        min(self.resource_list.index, max(0, len(self.resource_list.visible) - 1)))
        self.resource_list.selected.intersection_update(e.key for e in self.resource_list.entries if e.selectable)
        self._invalidate()

    def resource_refresh(self, force=False):
        if self.busy:
            return
        scope = self.resource_scope
        cached = self.resource_cache.get(scope)
        if cached and not force and time.monotonic() - cached[0] < resources.TTL:
            self._notice("Cached inventory. R refreshes local and upstream status.")
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self.resource_task is not None and not self.resource_task.done():
            if self.resource_scan_scope != scope:
                self._notice("Waiting for the previous workspace check to finish.")
            else:
                self._notice("Inventory check already running.")
            return
        self.resource_generation += 1
        self.resource_scan_scope = scope
        self.resource_task = self.tasks.start("resources", self.resource_scan(scope, self.resource_generation))
        self.resource_task.add_done_callback(self.resource_scan_finished)
        self._notice("Checking installed versions and available updates…", style="class:running")

    def resource_scan_finished(self, task):
        if task.cancelled() or task is not self.resource_task:
            return
        if self.screen == "resources" and self.resource_scope != self.resource_scan_scope:
            self.resource_refresh()

    async def resource_scan(self, scope, generation):
        try:
            rows = await asyncio.to_thread(resources.local_rows, scope)
            rows = await asyncio.to_thread(resources.scan, scope, rows)
        except Exception:
            if self.resource_scope == scope and generation == self.resource_generation:
                self._notice("Inventory check failed. R retries.", style="class:warning")
            return
        if generation != self.resource_generation:
            return
        self.resource_cache[scope] = (time.monotonic(), rows)
        self.resource_home_counts()
        if self.resource_scope == scope and self.screen in ("resources", "resource_detail", "resource_confirm", "help"):
            self.resource_rows = rows
            self.resource_render_rows()
            self._notice("Inventory refreshed. Unknown versions are never auto-updated.")

    def resource_home_counts(self):
        for scope, key in (("development", "environment"), ("ai", "agents")):
            cached = self.resource_cache.get(scope)
            if cached:
                count = sum(r.action == "Update" for r in cached[1])
                self.menu.entries = [replace(e, status=f"{count} updates" if count else "") if e.key == key else e
                                     for e in self.menu.entries]

    def resource_summary(self):
        rows = self.resource_rows
        return [("class:section", "  " + self.resource_title().upper() + "\n"),
                ("class:installed", f"  {sum(r.installation == 'Installed' for r in rows)} installed"),
                ("class:warning", f"  {sum(r.action == 'Update' for r in rows)} updates"),
                ("class:missing", f"  {sum(r.installation == 'Missing' for r in rows)} missing\n"),
                ("class:muted", f"  {len(self.resource_list.current_values)} selected · a recommended missing / u safe updates")]

    def resource_layout(self):
        if self.columns() >= WIDE_LAYOUT_MIN:
            return self._layout("resources-wide", lambda: VSplit([
                self.resource_list.window, self._divider_v(),
                self._text(self.resource_details, width=lambda: Dimension.exact(detail_panel_width(self.columns()))),
            ], padding=1))
        if self.rows() >= 25:
            return self._layout("resources-medium", lambda: HSplit([
                self.resource_list.window, self._divider(), self._text(self.resource_details, height=7)]))
        return self.resource_list.window

    def resource_details(self):
        row = next((r for r in self.resource_rows if r.key == self.resource_list.current_value), None)
        if not row:
            return [("class:muted", "  No matching resource.")]
        out = [("class:title", "  " + row.name + "\n\n"), (status_style(row.status), "  " + row.status + "\n"),
               ("class:body", "  " + (row.description or row.group.title()) + "\n\n"),
               ("class:section", "  LIFECYCLE\n"),
               ("class:body", "  Installed: " + (row.installed_version or "Unknown") + "\n"
                + "  Available: " + (row.available_version or "Unknown") + "\n"
                + "  Manager: " + (row.manager or "Unverified") + "\n"
                + "  Path: " + (row.path or "—") + "\n"
                + "  Recommended: " + ("Yes" if row.recommended else "Optional") + "\n"
                + "  Action: " + (row.action or "No automatic action") + "\n\n"),
               ("class:muted", "  " + row.evidence + "\n")]
        if row.integrations:
            out.append(("class:section", "\n  AGENT INTEGRATIONS\n"))
            for integration in row.integrations:
                out.append(("class:body", "  " + integration + "\n"))
            out.append(("class:muted", "  Default: Codex. E Advanced for other targets.\n"))
        return [(style, safe_text(value)) for style, value in out]

    def resource_show_details(self):
        self.resource_detail.text = "".join(text for _, text in self.resource_details())
        self.navigate("resource_detail", self.resource_detail)

    def resource_defaults(self):
        self.resource_list.current_values = [r.key for r in self.resource_rows if r.recommended and r.action in ("Install", "Configure")]
        self._notice("Selected recommended missing or incomplete resources.")

    def resource_updates(self):
        self.resource_list.selected.update(r.key for r in self.resource_rows if r.action == "Update")
        self._notice("Added all verified, safely updateable resources to selection.")

    def resource_advanced(self):
        self.resource_advanced_parent = True
        self.open_toolkit("Coding Agents" if self.resource_scope == "ai" else "Environment")

    def resource_review(self):
        if self.busy or (self.resource_task and not self.resource_task.done()):
            self._notice("Wait for the inventory check to finish before planning.")
            return
        try:
            self.resource_operations = resources.plan(self.resource_scope, self.resource_rows, self.resource_list.current_values)
        except ValueError as exc:
            self._notice(str(exc), style="class:warning")
            return
        self.resource_plan_text.text = "\n".join(
            f"{op.verb.upper():10} {op.name}\n  {shlex.join(op.command)}" for op in self.resource_operations)
        self.resource_plan_text.text += "\n\nUpdates use the original manager. Docker upgrades may restart the daemon.\nAI setup may install executable hooks; default target is global Codex.\nPonytail updates target Codex only; review /hooks after updating.\nSkill updates affect the named global skill (including agents sharing its directory)."
        self.resource_confirm.index = 0
        self.navigate("resource_confirm", self.resource_confirm.window)

    def resource_confirm_action(self):
        choice = self.resource_confirm.current_value
        if choice == "no":
            self.back()
            return
        if choice == "preview":
            self.resource_result.text = "DRY RUN — no commands executed\n\n" + self.resource_plan_text.text
            self.navigate("resource_result", self.resource_result)
            return
        if choice != "yes" or self.busy:
            return
        operations = tuple(op for op in self.resource_operations if op.command)
        if not operations:
            self._notice("No executable operations.")
            return
        self.busy = True
        self.resource_result.text = "Running confirmed operations…"
        self.navigate("resource_result", self.resource_result)
        self.run_task = asyncio.create_task(self.resource_execute(operations))

    async def resource_execute(self, operations):
        # The parent shell holds the existing operation lock across the batch.
        # Every argument is generated by the trusted catalog and shell-quoted.
        script = "set -e\nsource " + shlex.quote(str(ROOT / "utils/operation-lock.sh")) + "\ndevbox_acquire_lock\n"
        for op in operations:
            script += "printf '%s\\n' " + shlex.quote(op.verb + " " + op.name) + "\n" + shlex.join(op.command) + "\n"
        try:
            async with in_terminal():
                process = await asyncio.create_subprocess_exec("bash", "-c", script, cwd=str(ROOT))
                code = await process.wait()
            self.resource_result.text = ("Batch completed. Verify refreshed inventory." if code == 0
                else f"Batch stopped at the first failure (exit {code}). Later commands were not run.")
        except OSError as exc:
            self.resource_result.text = "Execution failed: " + safe_text(str(exc))
        finally:
            self.busy = False
            self.resource_cache.pop(self.resource_scope, None)
            self.resource_list.current_values = []
            self.resource_refresh(force=True)
            self._invalidate()

    def resource_back(self):
        if self.screen == "resources":
            if self.filter_active:
                self._cancel_filter()
            elif self.resource_list.query:
                self.resource_list.set_query("")
            else:
                self.navigate("home", self.menu.window)
        elif self.screen in ("resource_detail", "resource_confirm", "resource_result"):
            self.navigate("resources", self.resource_list.window)
            if self.screen == "resources" and not self.resource_cache.get(self.resource_scope):
                self.resource_refresh()
