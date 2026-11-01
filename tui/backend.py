"""Safe backend dispatch, structured events, and bounded log reads."""
from __future__ import annotations

import os
from pathlib import Path

from tui.catalog import COMPONENTS

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path.home() / ".local/state/devbox-bootstrap"
FINAL_STATES = {"INSTALLED", "CONFIGURED", "UPDATED", "UP_TO_DATE", "SKIPPED", "FAILED", "PLANNED", "NOT_RUN"}


def build_command(action: str, selected: list[str], *, dry_run: bool = False) -> list[str]:
    if action == "update":
        return ["bash", str(ROOT / "bin/devbox"), "--update"]
    if action in {"doctor", "preflight"}:
        return ["bash", str(ROOT / "setup-ubuntu.sh"), f"--{action}"]
    if action not in {"install", "upgrade"}:
        raise ValueError(f"Unknown action: {action}")
    allowed = {code for code, _ in COMPONENTS}
    if not selected or any(item not in allowed for item in selected):
        raise ValueError("Select at least one valid component.")
    cmd = ["bash", str(ROOT / "setup-ubuntu.sh")]
    if action == "upgrade":
        cmd.append("--upgrade")
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(["--only", ",".join(selected)])
    return cmd


def log_tail(path: Path | None, count: int = 14, *, max_bytes: int = 65536) -> str:
    if path is None or not path.is_file():
        return "No output yet."
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        block = stream.read().decode("utf-8", errors="replace")
    lines = block.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    return "\n".join(lines[-count:]) or "Waiting for output..."


def log_preview(path: Path, *, max_bytes: int = 1024 * 1024) -> str:
    """Show a bounded readable window; full contents remain on disk."""
    if not path.is_file():
        return "Log is missing."
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        data = stream.read().decode("utf-8", errors="replace")
    if size > max_bytes:
        data = data.partition("\n")[2]
        return "[Showing only the last 1 MiB; open the file with less for the full log]\n\n" + data
    return data or "(empty log)"


def read_events(path: Path | None, offset: int) -> tuple[list[tuple[str, str]], int]:
    if path is None or not path.is_file():
        return [], offset
    events: list[tuple[str, str]] = []
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        if offset > stream.tell():  # Log was truncated/replaced.
            offset = 0
        stream.seek(offset)
        while True:
            line = stream.readline()
            if not line or not line.endswith(b"\n"):
                break
            fields = line.decode("utf-8", errors="replace").strip().split("\t")
            if len(fields) == 3 and fields[0] == "STATUS" and all(fields[1:]):
                events.append((fields[1], fields[2]))
            offset = stream.tell()
    return events, offset
