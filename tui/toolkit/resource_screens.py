"""Shared direct-entry management screens for tools and agents."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import shlex
import sys
import time

from prompt_toolkit.layout import HSplit, DynamicContainer
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea

from tui.backend import ROOT
from tui.ui import Entry, KeyboardList, status_style
from tui.semantic import FragmentLexer, SemanticLexer
from .settings import inventory_ttl
from . import resources
from .native import safe_text
from .resource_batch import batch_command, needs_sudo, consent_entries


class ResourceScreens:
    def init_resources(self):
        self.resource_scope = "development"
        self.resource_filter = "All"
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
            on_update=self.resource_updates, on_retry=self.resource_retry_checks, on_cycle=self.resource_cycle_filter,
            on_refresh=lambda: self.resource_refresh(force=True),
            on_details=self.resource_show_details, on_edit=self.resource_advanced,
            on_adopt=self.resource_adopt,
            get_columns=self._component_list_width)
        self.resource_detail_lexer = FragmentLexer()
        self.resource_detail = TextArea(lexer=self.resource_detail_lexer, read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.resource_plan_text = TextArea(lexer=SemanticLexer("plan"), read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.resource_result = TextArea(lexer=SemanticLexer("plan"), read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        for field in (self.resource_detail, self.resource_plan_text, self.resource_result):
            self._bind_text(field)
        self.resource_options = KeyboardList([], multiple=True, bulk_select=False,
            on_enter=lambda: self.app.layout.focus(self.resource_confirm.window),
            on_back=self.back, on_help=self._show_help, on_change=self._invalidate,
            get_columns=self.columns)
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
        ]), lambda: self.resource_list.shortcut_hints(Enter="Review", a="Recommended", c="Retry updates", g="Status filter", e="Advanced") + "  Ctrl+K Search")
        self.views["resource_detail"] = self._page("Resource details", self.resource_detail, "↑↓ Scroll  Esc Back")
        self.views["resource_confirm"] = self._page("Review changes", DynamicContainer(self.resource_review_layout),
            "↑↓ Choose  Enter Confirm  Tab Focus  Space Options  Esc Back")
        self.views["resource_result"] = self._page("Resource operation result", self.resource_result, "↑↓ Scroll  Esc Back")

    def resource_review_layout(self):
        def build():
            children = [self.resource_plan_text, self._divider()]
            if self.resource_options.entries:
                children.extend([self._text(lambda: [("class:section", "  OPTIONAL PRIVILEGED ACTIONS (OFF BY DEFAULT)")], height=1),
                                 self.resource_options.window, self._divider()])
            children.append(self.resource_confirm.window)
            return HSplit(children)
        return self._layout("resource-review", build)

    def resource_prepare_confirmation(self):
        self.resource_options.entries = consent_entries(self.resource_operations)
        self.resource_options.current_values = []
        self.resource_options.index = 0
        self.resource_options.window.height = Dimension(min=1, preferred=len(self.resource_options.entries) + 1)
        self._layout_cache.pop("resource-review", None)
        self.resource_confirm.index = 0
        self.navigate("resource_confirm", self.resource_confirm.window)

    def resource_open(self, scope):
        if self.busy:
            return
        self.resource_scope = scope
        self.resource_advanced_parent = False
        self.resource_list.current_values = []
        self.resource_filter = "All"
        self.resource_list.entry_filter = None
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
            " ".join((r.description, r.installation, r.status, r.manager, r.evidence)), selectable=bool(r.action),
            status_parts=r.status_parts)
            for r in self.resource_rows]
        if self.resource_filter != "All":
            self.resource_apply_filter()
        self.resource_list.index = next((i for i, e in enumerate(self.resource_list.visible) if e.key == key),
                                        min(self.resource_list.index, max(0, len(self.resource_list.visible) - 1)))
        self.resource_list.selected.intersection_update(e.key for e in self.resource_list.entries if e.selectable)
        self._invalidate()

    def resource_refresh(self, force=False):
        if self.busy:
            return
        scope = self.resource_scope
        cached = self.resource_cache.get(scope)
        if cached and not force and time.monotonic() - cached[0] < inventory_ttl(self.preferences):
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
        if self.resource_scope == scope and self.screen in ("resources", "resource_detail", "resource_confirm", "resource_result", "help"):
            self.resource_rows = rows
            self.resource_render_rows()
            self._notice("Inventory refreshed. U selects verified updates; C selects retryable checks.")
        self._refresh_devbox_info()

    def resource_home_counts(self):
        for scope, key in (("development", "environment"), ("ai", "agents")):
            cached = self.resource_cache.get(scope)
            if cached:
                count = sum(r.verified_update for r in cached[1])
                self.menu.entries = [replace(e, status=f"{count} updates" if count else "") if e.key == key else e
                                     for e in self.menu.entries]

    def resource_summary(self):
        rows = self.resource_rows
        cached = self.resource_cache.get(self.resource_scope)
        freshness = f"{int(time.monotonic() - cached[0])}s ago" if cached else "Not checked"
        if self.resource_task and not self.resource_task.done() and self.resource_scan_scope == self.resource_scope:
            freshness = "Checking…"
        return [("class:section", "  " + self.resource_title().upper() + "  ·  "),
                ("class:muted", freshness + "\n"),
                ("class:installed", f"  {sum(r.installation == 'Installed' for r in rows)} installed"),
                ("class:warning", f"  {sum(r.verified_update for r in rows)} updates"),
                ("class:missing", f"  {sum(r.installation == 'Missing' for r in rows)} missing"),
                ("class:muted", f"  {sum(r.retry_update for r in rows)} retryable\n"),
                ("class:muted", f"  Filter: {self.resource_filter} · {len(self.resource_list.visible)}/{len(rows)} shown · {len(self.resource_list.current_values)} selected · g filter")]

    def resource_layout(self):
        return self._master_detail("resources", self.resource_list, self.resource_details, medium_height=7, min_columns=1)

    def resource_details(self):
        row = next((r for r in self.resource_rows if r.key == self.resource_list.current_value), None)
        if not row:
            return [("class:muted", "  No matching resource.")]
        out = [("class:title", "  " + row.name + "\n\n"),
               ("class:body", "  Installation: "), (status_style(row.installation), row.installation + "\n"),
               ("class:body", "  Update: "), (status_style(row.status), (("Up to date" if row.status == "Installed" else row.status) if row.installation == "Installed" else "Not applicable") + "\n"),
               ("class:body", "  " + (row.description or row.group.title()) + "\n\n"),
               ("class:section", "  LIFECYCLE\n"),
               ("class:body", "  Installed: " + (row.installed_version or "Unknown") + "\n"
                + "  Available: " + (row.available_version or "Unknown") + "\n"
                + "  Manager: " + (row.manager or "Unverified") + "\n"
                + "  Ownership: " + row.ownership + "\n"
                + "  Path: " + (row.path or "—") + "\n"
                + "  Recommended: " + ("Yes" if row.recommended else "Optional") + "\n"
                + "  Action: " + (("Check & update" if row.retry_update else row.action) or ("M — Adopt verified binary" if row.can_adopt else "No automatic action")) + "\n\n"),
               ("class:muted", "  " + row.evidence + "\n")]
        if row.integrations:
            out.append(("class:section", "\n  AGENT INTEGRATIONS\n"))
            for integration in row.integrations:
                out.append(("class:body", "  " + integration + "\n"))
            out.append(("class:muted", "  Default: Codex. E Advanced for other targets.\n"))
        return [(style, safe_text(value)) for style, value in out]

    def resource_show_details(self):
        self.resource_detail.text = self.resource_detail_lexer.set_fragments(self.resource_details())
        self.navigate("resource_detail", self.resource_detail)

    def resource_defaults(self):
        self.resource_list.selected.update(r.key for r in self.resource_rows if r.recommended and r.action in ("Install", "Configure"))
        self._notice("Selected recommended missing or incomplete resources.")

    def resource_updates(self):
        self.resource_list.selected.update(r.key for r in self.resource_rows if r.verified_update)
        self._notice("Selected verified available updates. C selects retryable checks separately.")

    def resource_retry_checks(self):
        self.resource_list.selected.update(r.key for r in self.resource_rows if r.retry_update)
        self._notice("Selected retryable update candidates. Review may run the verified provider.")

    def resource_cycle_filter(self):
        filters = ("All", "Installed", "Missing", "Updates", "Needs attention")
        self.resource_filter = filters[(filters.index(self.resource_filter) + 1) % len(filters)]
        self.resource_apply_filter()

    def resource_apply_filter(self):
        rows = {r.key: r for r in self.resource_rows}
        def matches(entry):
            row = rows.get(entry.key)
            if not row:
                return False
            return {
                "All": True, "Installed": row.installation == "Installed",
                "Missing": row.installation == "Missing",
                "Updates": row.verified_update,
                "Needs attention": row.status in ("Update blocked", "Update unknown", "Check failed", "Partial", "Unverified", "Disabled"),
            }[self.resource_filter]
        self.resource_list.entry_filter = None if self.resource_filter == "All" else matches
        self.resource_list.index = 0
        self._invalidate()

    def resource_advanced(self):
        self.resource_advanced_parent = True
        self.open_toolkit("Coding Agents" if self.resource_scope == "ai" else "Environment")

    def resource_adopt(self):
        if self.busy or (self.resource_task and not self.resource_task.done()):
            self._notice("Wait for inventory to finish.", style="class:warning")
            return
        row = next((r for r in self.resource_rows if r.key == self.resource_list.current_value), None)
        if not row or not row.can_adopt:
            self._notice("This resource cannot be adopted automatically.", style="class:warning")
            return
        cmd = ("bash", str(ROOT / "utils/adopt-binary.sh"), sys.executable, row.key, row.installed_version)
        self.resource_operations = (resources.Operation("Adopt", row.key, row.name, cmd),)
        self.resource_plan_text.text = "ADOPT " + row.name + "\n" + row.path + "\nVersion: " + row.installed_version + "\n\nVerify official release SHA-256 and register ownership. No binary replacement.\n" + shlex.join(cmd)
        self.resource_prepare_confirmation()

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
        retry_count = sum(r.retry_update and r.key in self.resource_list.current_values for r in self.resource_rows)
        if retry_count:
            self.resource_plan_text.text += f"\n\nWarning: {retry_count} selected update candidates have no confirmed newer version; the provider will check again."
        self.resource_plan_text.text += "\n\nUpdates use the original manager. Current tools can be explicitly checked. Legacy Kubernetes binaries are checksum-verified before replacement. Docker upgrades may restart the daemon.\nAI setup may install executable hooks; default target is global Codex.\nPonytail updates target Codex only; review /hooks after updating.\nSkill updates affect the named global skill (including agents sharing its directory)."
        self.resource_prepare_confirmation()

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
        self.resource_execute(self.resource_operations)

    def resource_execute(self, operations):
        """Dispatch the reviewed plan to the existing fullscreen execution engine."""
        if self.busy:
            return
        self.dry_run = False
        self._start_command("resources", batch_command(operations), [op.key for op in operations],
                            resource_scope=self.resource_scope,
                            labels={op.key: op.verb + " " + op.name for op in operations},
                            consent=set(self.resource_options.current_values),
                            needs_sudo=needs_sudo(operations, self.resource_scope))

    def resource_back(self):
        if self.screen == "resources":
            if self.filter_active:
                self._cancel_filter()
            elif self.resource_list.query:
                self.resource_list.set_query("")
            elif self.resource_filter != "All":
                self.resource_filter = "All"
                self.resource_apply_filter()
                self._notice("Status filter cleared. Esc returns.")
            else:
                self.navigate("home", self.menu.window)
        elif self.screen == "resource_result":
            self.navigate("resource_confirm", self.resource_confirm.window)
        elif self.screen in ("resource_detail", "resource_confirm"):
            self.navigate("resources", self.resource_list.window)
            if self.screen == "resources" and not self.resource_cache.get(self.resource_scope):
                self.resource_refresh()
