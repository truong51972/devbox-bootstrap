"""Shared input, help and result presentation for toolkit screens."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from prompt_toolkit.completion import WordCompleter, PathCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, DynamicContainer
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea

from tui.agent_status import AGENTS
from tui.semantic import FragmentLexer
from tui.ui import Entry, KeyboardList
from tui.views import WIDE_LAYOUT_MIN
from .guidance import MODULES, guide_for, command_example
from .registry import BY_ID
from .native import safe_text
from .network import port_number, endpoint
from .results import TableData
from .result_view import ResultTable, fragments


def action_help(key):
    guide = guide_for(key)
    if not guide:
        return []
    out = [("class:section", "  WHEN TO USE\n"), ("class:body", "  " + guide.use + "\n\n"),
           ("class:section", "  EXPECTED RESULT\n"), ("class:body", "  " + guide.result + "\n\n")]
    if guide.example:
        out.extend([("class:section", "  EXAMPLE\n"), ("class:body", "  " + guide.example + "\n\n")])
    out += [("class:section", "  LIMITATIONS\n"), ("class:warning", "  " + guide.limit + "\n")]
    if key in BY_ID:
        out += [("class:section", "\n  CLI\n"), ("class:body", "  " + command_example(key, guide) + "\n")]
    return out


def validate_form(key, value):
    guide = guide_for(key)
    if not guide:
        return value
    if guide.kind != "editor":
        value = value.strip()
    if key in BY_ID and BY_ID[key].required and not value.strip():
        raise ValueError("Enter a value before running.")
    if guide.kind == "port":
        port_number(value)
    elif guide.kind == "pid" and (not value.isascii() or not value.isdigit() or int(value) <= 1):
        raise ValueError("Enter a valid PID greater than 1.")
    elif guide.kind in ("endpoint", "tls"):
        endpoint(value, 443 if guide.kind == "tls" else None)
    elif guide.kind == "host" and (not value or value.startswith("-") or any(c.isspace() for c in value)):
        raise ValueError("Enter a hostname or IP address without spaces.")
    elif guide.kind == "url":
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter an HTTP(S) URL without credentials.")
    elif guide.kind == "agent" and value not in AGENTS:
        raise ValueError("Choose one of: " + ", ".join(AGENTS))
    elif guide.kind == "scope" and value not in ("", "global", "project"):
        raise ValueError("Choose global or project.")
    return value


class ToolkitUX:
    def init_ux(self):
        self.ux_value = ""
        self.ux_result = None
        self.ux_raw_parent = "toolkit_result"
        self.ux_detail_parent = "toolkit_table"
        self.ux_editor = False
        self.ux_form_kind = "none"
        self.ux_line = TextArea(multiline=False, height=1)
        self.ux_port = TextArea(multiline=False, height=1)
        self.ux_editor_output = TextArea(read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.ux_result_lexer = FragmentLexer()
        self.ux_detail_lexer = FragmentLexer()
        self.ux_detail = TextArea(lexer=self.ux_detail_lexer, read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self.ux_raw = TextArea(read_only=True, focusable=True, scrollbar=True, wrap_lines=True)
        self._bind_text(self.ux_detail)
        @self.ux_detail.control.key_bindings.add("x")
        def _row_actions(_event):
            self.ux_open_related()
        self._bind_text(self.ux_raw)
        self.ux_table = ResultTable([], on_enter=self.ux_show_row, on_back=self.back,
            on_help=self._show_help, on_change=self._invalidate, on_filter=self._begin_filter,
            on_refresh=self.ux_repeat, on_details=self.ux_show_row, on_sort=self.ux_sort,
            on_raw=self.ux_show_raw, on_related=self.ux_open_related, on_edit=self.ux_edit,
            get_columns=lambda: self.columns())
        self.ux_related = KeyboardList([], on_enter=self.ux_run_related, on_back=self.back,
            on_help=self._show_help, on_change=self._invalidate, get_columns=self.columns)
        self.ux_related_parent = "toolkit_result"
        self.ux_targets = {}
        self.inventory_operations = False
        self.inventory_target = None
        self.ux_stack = []
        self.ux_legacy_parent = None
        self.ux_help_focus = None
        self.ux_phase = "Ready"
        for field in (self.ux_line, self.ux_port):
            bindings = KeyBindings()
            @bindings.add("enter", eager=True)
            def _run(_event):
                self.toolkit_submit()
            @bindings.add("escape", eager=True)
            def _back(_event):
                self.back()
            @bindings.add("tab", eager=True)
            @bindings.add("s-tab", eager=True)
            def _tab(_event):
                if self.ux_form_kind in ("endpoint", "tls"):
                    self.app.layout.focus(self.ux_port if self.app.layout.has_focus(self.ux_line) else self.ux_line)
                elif self.ux_line.buffer.completer:
                    self.ux_line.buffer.start_completion(select_first=False)
            field.control.key_bindings = bindings

        keys = KeyBindings()
        @keys.add("escape", eager=True)
        def _close(_event):
            self.back()
        @keys.add("c-s", eager=True)
        def _submit(_event):
            self.toolkit_submit()
        @keys.add("tab", eager=True)
        def _focus(_event):
            self.app.layout.focus(self.toolkit_input)
        @keys.add("c-c", eager=True)
        def _copy(_event):
            self.app.clipboard.set_text(self.ux_editor_output.text)
            self._notice("Copied output to Devbox clipboard.")
        self.ux_editor_output.control.key_bindings = keys

    def ux_title(self):
        key = self.toolkit_key
        if key in BY_ID:
            return BY_ID[key].label
        if key.startswith("run:"):
            return key[4:]
        return key.replace(".", " ").replace("legacy:", "").title()

    def ux_path(self, suffix=""):
        action = BY_ID.get(self.toolkit_key)
        category = action.category if action else self.toolkit_category or "Quick actions"
        return category + " / " + self.ux_title() + (" / " + suffix if suffix else "")

    def ux_module_intro(self):
        title = "AI Agents" if self.toolkit_category == "Coding Agents" else self.toolkit_category or "Quick actions"
        intro = MODULES.get(self.toolkit_category, ("Search the complete action catalog by goal, name or command.", ()))[0]
        return [("class:title", "  " + title.upper() + "\n"),
                ("class:body", "  " + intro + "\n"),
                ("class:muted", "  Select an action for examples and limitations. ? Help")]

    def ux_help(self, screen, application=False):
        out = []
        if not application and screen.startswith("toolkit"):
            key = self.toolkit_list.current_value if screen == "toolkit" else self.toolkit_key
            category = self.toolkit_category or "Quick actions"
            intro, cases = MODULES.get(category, ("Search by action, use case or command.", ()))
            out += [("class:title", "  " + ("AI Agents" if category == "Coding Agents" else category).upper() + "\n\n"), ("class:body", "  " + intro + "\n\n")]
            if cases:
                out.append(("class:section", "  COMMON TASKS\n"))
                for case, action in cases:
                    label = BY_ID[action].label if action in BY_ID else action.removeprefix("legacy:").title()
                    out += [("class:body", "  " + case + "\n"), ("class:running", "    → " + label + "\n")]
            if key and guide_for(key):
                out += [("class:title", "\n  " + (BY_ID[key].label if key in BY_ID else key) + "\n\n")]
                out += action_help(key)
        elif not application:
            topics = {
                "home": ("Overview", "Development Tools and AI Agents share Manage. Info shows the workstation summary. R checks Devbox source updates again; U on Info reviews a source update; Enter opens the full Info page or selected action. Source updates are fast-forward only and exit on success."),
                "resources": ("Manage resources", "Space selects a resource; a selects recommended missing/incomplete items; u adds verified updates; c selects retryable checks; g cycles status filters; n clears; r refreshes; i shows details; e opens advanced tools; Enter reviews the plan. No changes occur without explicit confirmation."),
                "resource_confirm": ("Review changes", "Choose dry run to inspect commands or Execute to apply the exact reviewed batch."),
                "select": ("Select components", "Space toggles an item. Review dependencies and consent before applying."),
                "cleaner": ("Safe cleanup", "Scan first. a selects eligible safe cleaners only. Manual resources require exact selection and explicit consent."),
                "confirm": ("Review changes", "Check exact targets and optional changes. d switches dry-run when supported. Enter executes the displayed plan."),
                "logs": ("Activity", "Choose a saved run to inspect its report and log. Query inputs and outputs are not saved."),
                "result": ("Operation result", "Review each outcome; use l for the full log. A successful command is not necessarily a verified resource state."),
                "view_log": ("Raw log", "Scroll or open an external pager. Native log lines may contain sensitive information."),
            }
            if screen in topics:
                title, description = topics[screen]
                out += [("class:title", "  " + title.upper() + "\n\n"), ("class:body", "  " + description + "\n\n")]
        lists = {"home": self.menu, "resources": self.resource_list, "select": self.selector,
                 "cleaner": self.cleaner_list, "logs": self.log_files, "toolkit": self.toolkit_list,
                 "toolkit_ai_setup": self.ai_setup_list, "toolkit_tools": self.inventory_list,
                 "toolkit_matrix": self.inventory_list, "toolkit_table": self.ux_table}
        widget = lists.get(screen)
        if not application and widget is not None:
            labels = {"home": {"r": "Check source", "u": "Review source" if self.menu.current_value == "devbox_info" else ""},
                      "resources": {"Enter": "Review", "a": "Recommended", "c": "Retry updates", "e": "Advanced"},
                      "select": {"Enter": "Review", "a": "All filtered"},
                      "cleaner": {"Enter": "Review", "a": "Safe preset", "r": "Scan"},
                      "toolkit_ai_setup": {"Enter": "Review", "a": "Codex preset"},
                      "logs": {"Enter": "View log"}, "toolkit_table": {"Enter": "Details", "x": "Related"},
                      "toolkit_tools": {"Enter": "Details"}, "toolkit_matrix": {"Enter": "Details"}}
            out.append(("class:section", "\n  AVAILABLE SHORTCUTS\n"))
            for part in widget.shortcut_hints(**labels.get(screen, {})).split("  "):
                key, sep, label = part.partition(" ")
                out.extend([("class:key", "  " + key), ("class:body", sep + label + "\n")])
        out += [("class:section", "\n  KEYBOARD\n"),
                ("class:body", "  Enter  Open / run / confirm\n  Esc    Back\n  ↑↓     Navigate or scroll\n  /      Filter lists\n  ?      Context help (list/result)\n  F1     Context help, including editing\n  i      Full details when available\n  x      Related actions when available\n  Ctrl+K Search from home or catalog\n  Ctrl+S Run multiline editor\n  Tab    Change form/editor focus\n  Ctrl+Q Quit\n")]
        return out

    def ux_open_form(self, value=""):
        guide = guide_for(self.toolkit_key)
        self.ux_form_kind = guide.kind if guide else "line"
        self.ux_editor = self.ux_form_kind == "editor"
        self.toolkit_input.text = value if self.ux_editor else ""
        self.ux_editor_output.text = ""
        self.ux_line.text = ""
        self.ux_port.text = ""
        self._layout_cache.pop("ux-form", None)
        self.ux_line.buffer.completer = None
        if self.ux_form_kind == "path":
            self.ux_line.buffer.completer = PathCompleter(expanduser=True, get_paths=lambda: [self.toolkit_cwd])
        elif self.ux_form_kind == "agent":
            self.ux_line.buffer.completer = WordCompleter(list(AGENTS))
        elif self.ux_form_kind == "scope":
            self.ux_line.buffer.completer = WordCompleter(["global", "project"])
            value = value or "global"
        if self.ux_form_kind in ("endpoint", "tls"):
            if value:
                try:
                    host, port = endpoint(value, 443 if self.ux_form_kind == "tls" else None)
                    self.ux_line.text, self.ux_port.text = host, str(port)
                except ValueError:
                    self.ux_line.text = value
            elif self.ux_form_kind == "tls":
                self.ux_port.text = "443"
        elif not self.ux_editor:
            self.ux_line.text = value
        self.navigate("toolkit_input", self.toolkit_input if self.ux_editor else self.ux_line)

    def ux_form(self):
        return self._layout("ux-form", self._build_ux_form)

    def _build_ux_form(self):
        if self.ux_editor:
            return HSplit([self._text(lambda: [("class:section", "  INPUT   ·   Ctrl+S run"), ("class:muted", "   " + guide_for(self.toolkit_key).limit)], height=2),
                           DynamicContainer(self.ux_editor_layout)])
        guide = guide_for(self.toolkit_key)
        fields = [self._text(lambda: [("class:section", "  Hostname or IP" if self.ux_form_kind in ("endpoint", "tls") else "  " + (BY_ID[self.toolkit_key].prompt if self.toolkit_key in BY_ID else "Exact target"))], height=1), self.ux_line]
        if self.ux_form_kind in ("endpoint", "tls"):
            fields += [self._text(lambda: [("class:section", "  Port (1–65535)")], height=1), self.ux_port]
        if guide and guide.example:
            fields += [self._text(lambda: [("class:muted", "  Example: " + guide.example)], height=2)]
        fields += [self._text(lambda: [("class:warning", "  " + guide.limit)] if guide else [], height=Dimension(min=2, preferred=4)),
                   self._text(lambda: [("class:muted", "  Enter run · F1 help · Esc back")])]
        return HSplit(fields)

    def ux_editor_layout(self):
        def output():
            return HSplit([self._text(lambda: [("class:section", "  OUTPUT   ·   Ctrl+C copy (output focus)")], height=1), self.ux_editor_output])
        if self.columns() >= WIDE_LAYOUT_MIN:
            return self._layout("ux-editor-wide", lambda: VSplit([self.toolkit_input, self._divider_v(), output()], padding=1))
        return self._layout("ux-editor-narrow", lambda: HSplit([self.toolkit_input, self._divider(), output()]))

    def ux_input_value(self):
        if self.ux_editor:
            return self.toolkit_input.text
        if self.ux_form_kind in ("endpoint", "tls"):
            host, port = self.ux_line.text.strip(), self.ux_port.text.strip()
            if ":" in host and not host.startswith("["):
                host = "[" + host + "]"
            return host + ":" + port
        return self.ux_line.text if self.ux_form_kind != "none" else ""

    def ux_clear_input(self):
        self.toolkit_input.text = ""
        self.ux_line.text = ""
        self.ux_port.text = ""
        self.ux_editor_output.text = ""
        self.ux_editor = False
        self.ux_form_kind = "none"
        self._layout_cache.pop("ux-form", None)

    def ux_submit_value(self, key, value):
        action = BY_ID.get(key)
        self.ux_value = "" if action and action.sensitive else value
        self.ux_result = None
        self.ux_phase = "Running"
        if self.ux_editor:
            self.ux_editor_output.text = "Running…"
        else:
            self.ux_clear_input()
            self.toolkit_result.text = "Checking…" if key not in BY_ID else "Running…"
            self.navigate("toolkit_result", self.toolkit_result)
        self.toolkit_task = asyncio.create_task(self.toolkit_query(key, value))

    def ux_repeat(self):
        if self.busy or self.toolkit_running():
            return
        action = BY_ID.get(self.toolkit_key)
        if not action:
            self._notice("Reopen this operation to review a new plan.")
            return
        if action.sensitive and action.prompt:
            self.ux_edit()
            return
        if self.screen == "toolkit_table":
            self._notice("Refreshing…", style="class:running")
            self.toolkit_task = asyncio.create_task(self.toolkit_query(action.id, self.ux_value))
        else:
            self.ux_submit_value(action.id, self.ux_value)

    def ux_edit(self):
        action = BY_ID.get(self.toolkit_key)
        if self.busy or self.toolkit_running() or not action or not action.prompt:
            self._notice("This action has no editable input.")
            return
        self.ux_open_form(self.ux_value)

    def ux_present(self, result):
        self.ux_result = result
        self.ux_phase = "Completed" if result.tone != "error" else "Check result"
        if isinstance(result.data, TableData):
            preserve = self.screen == "toolkit_table"
            self.ux_table.set_data(result.data, preserve=preserve)
            if not preserve:
                self.filter_active = False
                self.navigate("toolkit_table", self.ux_table.window)
        else:
            self.toolkit_result.text = self.ux_result_lexer.set_fragments(fragments(result, self.columns()))
        self._notice(result.summary, style="class:" + result.tone)

    def ux_result_summary(self):
        guide = guide_for(self.toolkit_key)
        tone = {"Running": "running", "Completed": "installed", "Failed": "error", "Check result": "warning"}.get(self.ux_phase, "muted")
        return [("class:title", "  " + self.ux_title() + "\n"), ("class:" + tone, "  " + self.ux_phase + "\n"),
                ("class:muted", "  " + (guide.result if guide else "Review the operation outcome."))]

    def ux_table_summary(self):
        result = self.ux_result
        if not result:
            return []
        visible = len(self.ux_table.visible)
        total = len(self.ux_table.entries)
        return [("class:" + result.tone, "  " + safe_text(result.summary) + "\n"),
                ("class:muted", f"  {visible}/{total} rows · Enter details · x related actions\n"),
                ("class:warning" if result.partial else "class:muted", "  " + safe_text(" · ".join(result.notes) or "Snapshot · refresh to check again"))]

    def ux_sort(self):
        self.ux_table.sort_next()
        if self.ux_table.sort_column >= 0:
            self._notice("Sorted by " + self.ux_table.data.columns[self.ux_table.sort_column])

    def ux_show_row(self):
        if self.ux_table.row is None:
            return
        self.ux_detail_parent = self.screen
        self.ux_detail.text = self.ux_detail_lexer.set_fragments(self.ux_table.detail())
        self.navigate("toolkit_row_detail", self.ux_detail)

    def ux_show_raw(self):
        if not self.ux_result or not self.ux_result.raw:
            self._notice("No separate native output is available.")
            return
        self.ux_raw_parent = self.screen
        self.ux_raw.text = safe_text(self.ux_result.raw)
        self.navigate("toolkit_raw", self.ux_raw)

    def ux_open_related(self):
        guide = guide_for(self.toolkit_key)
        if not guide or not guide.related or self.toolkit_running():
            self._notice("No related action available.")
            return
        self.inventory_operations = False
        self.ux_related_parent = "toolkit_table" if self.screen == "toolkit_row_detail" else self.screen
        row = self.ux_table.row if self.screen in ("toolkit_table", "toolkit_row_detail") else None
        values = dict(zip(self.ux_table.data.columns, (c.value for c in row))) if row else {}
        self.ux_targets = {}
        entries = []
        for key in guide.related:
            if key == "legacy:clean":
                entries.append(Entry(key, "Open Cleaner — review cleanup targets"))
                continue
            if key.startswith(("legacy:", "run:")):
                continue
            target = ""
            if key.startswith("docker.") and key != "docker.ps":
                target = values.get("ID", "") or values.get("Name", "")
            elif key == "sys.terminate":
                target = values.get("PID", "")
                if not target.isdigit():
                    continue
            elif key == "net.port":
                target = values.get("Port", "")
            elif key == "agent.version":
                target = values.get("Agent ID", "")
                if not target:
                    continue
            self.ux_targets[key] = target
            entries.append(Entry(key, BY_ID[key].label if key in BY_ID else key, description=target))
        if not entries:
            self._notice("Open the module to choose a related managed action.")
            return
        self.ux_related.entries = entries
        self.ux_related.set_query("")
        self.navigate("toolkit_related", self.ux_related.window)

    def ux_run_related(self):
        if self.inventory_operations:
            self.inventory_apply_action()
            return
        key = self.ux_related.current_value
        if not key:
            return
        if key == "legacy:clean":
            self.ux_legacy_parent = self.ux_related_parent
            self.open_menu("clean")
            return
        action = BY_ID.get(self.toolkit_key)
        if action and not action.sensitive:
            self.ux_stack.append((self.toolkit_key, self.ux_value, self.ux_result, self.ux_related_parent,
                                  self.ux_table.query, self.ux_table.index, self.ux_table.sort_column, self.ux_table.row))
        self.toolkit_key = key
        self.ux_result = None
        self.ux_value = ""
        target = self.ux_targets.get(key, "")
        self.ux_clear_input()
        if guide_for(key).kind == "none":
            self.ux_submit_value(key, "")
        else:
            self.ux_open_form(target)

    def ux_restore_parent(self):
        if not self.ux_stack:
            return False
        key, value, result, screen, query, index, sort_column, row = self.ux_stack.pop()
        self.toolkit_key, self.ux_value, self.ux_result = key, value, result
        if screen == "toolkit_table" and result and isinstance(result.data, TableData):
            self.ux_table.set_data(result.data)
            self.ux_table.set_query(query)
            if sort_column >= 0:
                self.ux_table.sort_by(sort_column)
            self.ux_table.index = next((i for i, entry in enumerate(self.ux_table.visible) if self.ux_table.data.rows[int(entry.key)] == row), min(index, max(0, len(self.ux_table.visible) - 1)))
        elif result:
            self.toolkit_result.text = self.ux_result_lexer.set_fragments(fragments(result, self.columns()))
        self.ux_phase = "Completed"
        self.navigate(screen, self._focus_for(screen))
        return True
