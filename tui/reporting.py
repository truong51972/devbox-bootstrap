"""Structured per-run summary; raw logs remain the source of verbose output."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class RunReport:
    action: str
    started: str
    duration: float
    exit_code: int | None
    dry_run: bool
    status: dict[str, str]
    details: dict[str, str]
    message: str

    @property
    def heading(self):
        if self.exit_code != 0 or any(v == "FAILED" for v in self.status.values()):
            return "FAILED"
        if self.dry_run and self.action in {"install", "upgrade", "clean"}:
            return "PREVIEW"
        if any(v in {"SKIPPED", "NOT_RUN"} for v in self.status.values()):
            return "PARTIAL"
        return "SUCCESS"


def summarize_status(status):
    counts = {}
    for value in status.values():
        if value != "--":
            counts[value] = counts.get(value, 0) + 1
    return " | ".join(f"{n} {state.lower().replace('_', ' ')}" for state, n in counts.items()) or "No component-level events"


def status_lines(action, status, labels, details):
    rows = [f"  {action or 'Idle'}", ""]
    for code, value in status.items():
        if value == "--":
            continue
        marker = "✓" if value in {"INSTALLED", "CONFIGURED", "UPDATED", "UP_TO_DATE", "CLEANED", "COMPLETED"} else (
            "!" if value == "FAILED" else ">" if value == "RUNNING" else "·")
        rows.append(f"  {marker}  {labels.get(code, code):<26} {value}")
        if code in details:
            rows.append("       " + details[code])
    return "\n".join(rows) if len(rows) > 2 else "Waiting for status events..."


def write_report(log_path: Path, report: RunReport):
    target = log_path.with_suffix(".json")
    fd, name = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schema": 1, **asdict(report)}, stream)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def read_report(log_path: Path):
    path = log_path.with_suffix(".json")
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.pop("schema", None) != 1:
            return None
        report = RunReport(**payload)
        if (not isinstance(report.duration, (int, float)) or not isinstance(report.status, dict)
                or not isinstance(report.details, dict)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in report.status.items())
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in report.details.items())):
            return None
        return report
    except (OSError, ValueError, TypeError, AttributeError):
        return None
