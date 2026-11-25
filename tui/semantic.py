"""Semantic formatting for scrollable, read-only Devbox text views.

Keep the original buffer text, cursor, scroll and raw log unchanged. Only
recognize structured status rows or explicit log severity prefixes.
"""
from __future__ import annotations

import re

from prompt_toolkit.lexers import Lexer
from prompt_toolkit.formatted_text.utils import split_lines

from tui.ui import STATUS_STYLES

_STATES = "|".join(sorted((re.escape(s) for s in STATUS_STYLES if s.isupper()), key=len, reverse=True))
_ROW = re.compile(r"^(\s*)([✓!>·])(\s+.*?\s+)(" + _STATES + r")$")
_HEADING = re.compile(r"^(\s*)(" + _STATES + r")(?= — )")
_COUNT = re.compile(r"\b\d+ (" + "|".join(
    sorted((re.escape(s.lower().replace("_", " ")) for s in STATUS_STYLES if s.isupper()), key=len, reverse=True)
) + r")(?= \||$)")
_LOG_LEVEL = re.compile(r"^\s*(?:\[devbox\]\s*)?(?:\[(ERROR|WARN(?:ING)?|INFO|SUCCESS|OK)\]|(ERROR|WARN(?:ING)?|INFO|SUCCESS|OK):)(?:\s|$)", re.I)
_SECTION = {"LAST OUTPUT", "RECENT OUTPUT", "EXPANDED OUTPUT", "OVERVIEW", "DESCRIPTION",
            "INVENTORY", "INSTALLATION", "NOTE", "QUICK ACTIONS", "AGENT INTEGRATIONS",
            "COMPONENT DETAILS", "SELECTED RUN"}


def _style(state: str) -> str:
    return STATUS_STYLES.get(state, "class:body")


def log_fragments(line: str) -> list[tuple[str, str]]:
    match = _LOG_LEVEL.match(line)
    if match:
        level = (match[1] or match[2]).upper()
        style = ("class:error" if level == "ERROR" else
                 "class:warning" if level.startswith("WARN") else
                 "class:installed" if level in ("OK", "SUCCESS") else "class:running")
        return [(style, line)]
    return [("class:body", line)]


def count_fragments(line: str) -> list[tuple[str, str]]:
    out = []
    offset = 0
    for match in _COUNT.finditer(line):
        out.extend([("class:muted", line[offset:match.start()]),
                    (_style(match[1].upper().replace(" ", "_")), match[0])])
        offset = match.end()
    out.append(("class:muted", line[offset:]))
    return out


def report_fragments(line: str) -> list[tuple[str, str]]:
    row = _ROW.fullmatch(line)
    if row:
        style = _style(row[4])
        return [("class:body", row[1]), (style, row[2]),
                ("class:body", row[3]), (style, row[4])]
    heading = _HEADING.match(line)
    if heading:
        return [("class:body", heading[1]), (_style(heading[2]), heading[2]),
                ("class:title", line[heading.end():])]
    if line.strip().startswith("Duration:"):
        return count_fragments(line)
    if line.strip() in _SECTION:
        return [("class:section", line)]
    if line.strip().startswith("Full log:"):
        return [("class:muted", line)]
    if line.strip().lower() in ("install", "upgrade", "clean", "update", "idle"):
        return [("class:title", line)]
    if line.startswith("       "):
        return [("class:muted", line)]
    return [("class:body", line)]


def plan_fragments(line: str) -> list[tuple[str, str]]:
    text = line.strip()
    if text.startswith(("SAFE ", "MANUAL ")):
        indent = len(line) - len(line.lstrip())
        token = text.split()[0]
        return [("class:body", line[:indent]),
                ("class:installed" if token == "SAFE" else "class:warning", token),
                ("class:body", line[indent + len(token):])]
    if text.startswith(("DRY RUN", "Warning:", "Sudo authentication required", "Manual items require",
                        "Select exact", "Select an agent target", "Unavailable safe cleaners")):
        return [("class:warning", line)]
    token = text.split(maxsplit=1)[0] if text else ""
    if token in ("INSTALL", "CONFIGURE", "UPDATE", "ADOPT", "SKIP"):
        return [("class:warning" if token in ("UPDATE", "ADOPT", "SKIP") else "class:running", line)]
    if text.startswith(("Install:", "Upgrade:", "Clean:", "Update Devbox source")):
        return [("class:title", line)]
    if text.startswith(("Apply selected changes", "Agent targets:")):
        return [("class:running", line)]
    return [("class:body", line)]


class SemanticLexer(Lexer):
    def __init__(self, mode: str):
        self.mode = mode

    def lex_document(self, document):
        lines = document.lines
        # Result's raw output section is intentionally not parsed as report data.
        boundary = next((i for i, line in enumerate(lines) if line.strip() == "LAST OUTPUT"), len(lines)) if self.mode == "result" else len(lines)

        def get_line(index):
            if not 0 <= index < len(lines):
                return []
            line = lines[index]
            if self.mode == "log" or index > boundary:
                return log_fragments(line)
            if self.mode == "plan":
                return plan_fragments(line)
            return report_fragments(line)
        return get_line


class FragmentLexer(Lexer):
    """Preserve styles from an existing formatted detail renderer."""
    def __init__(self):
        self.lines = []
        self.text = ""
        self.revision = 0

    def set_fragments(self, fragments):
        self.text = "".join(text for _, text in fragments)
        self.lines = list(split_lines(fragments))
        self.revision += 1
        return self.text

    def invalidation_hash(self):
        return (id(self), self.revision)

    def lex_document(self, document):
        lines = self.lines if document.text == self.text else None
        def get_line(index):
            if not 0 <= index < len(document.lines):
                return []
            if lines is not None and index < len(lines):
                return lines[index]
            return [("class:body", document.lines[index])]
        return get_line
