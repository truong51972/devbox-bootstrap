"""Lightweight full-screen UI over the existing Bash bootstrap.

No package mutations happen in this module: all installers run in isolated
subprocesses and append their unfiltered output to on-disk log files.
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
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, CheckboxList, Frame, Label, TextArea

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path.home() / ".local" / "state" / "devbox-bootstrap"
COMPONENTS = (
    ("zsh", "Zsh + Oh My Zsh"),
    ("powerlevel10k", "Powerlevel10k"),
    ("uv", "uv (Python)"),
    ("keychain", "SSH keychain"),
    ("zoxide", "zoxide"),
    ("fzf", "fzf"),
    ("ripgrep", "ripgrep"),
    ("bat-fd", "bat + fd"),
    ("docker", "Docker Engine"),
    ("nvidia", "NVIDIA Toolkit"),
    ("kubectl", "kubectl"),
    ("minikube", "Minikube"),
    ("direnv", "direnv"),
)
FINISHED_STATES = {"INSTALLED", "CONFIGURED", "UPDATED", "UP_TO_DATE", "SKIPPED", "FAILED", "PLANNED"}


def build_command(action: str, selected: list[str], *, dry_run: bool = False) -> list[str]:
    """Construct a backend command without a shell or user-controlled syntax."""
    if action == "update":
        return ["bash", str(ROOT / "bin" / "devbox"), "--update"]
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


def log_tail(path: Path | None, count: int = 14) -> str:
    """Read a bounded suffix; never load a large APT log into UI memory."""
    if path is None or not path.is_file():
        return "No output yet."
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - 65536))
        block = stream.read().decode("utf-8", errors="replace")
    lines = block.splitlines()
    if size > 65536 and lines:
        lines = lines[1:]
    return "\n".join(lines[-count:]) or "Waiting for output..."


def read_events(path: Path | None, offset: int) -> tuple[list[tuple[str, str]], int]:
    if path is None or not path.is_file():
        return [], offset
    events: list[tuple[str, str]] = []
    with path.open("rb") as stream:
        stream.seek(offset)
        while True:
            line = stream.readline()
            if not line or not line.endswith(b"\n"):
                break  # Wait for a complete event line before consuming it.
            fields = line.decode("utf-8", errors="replace").strip().split("\t")
            if len(fields) == 3 and fields[0] == "STATUS":
                events.append((fields[1], fields[2]))
            offset = stream.tell()
    return events, offset


class DevboxTUI:
    def __init__(self) -> None:
        self.selector = CheckboxList(COMPONENTS)
        self.status: dict[str, str] = {code: "--" for code, _ in COMPONENTS}
        self.message = "Select components with Space, then choose Install or Upgrade."
        self.busy = False
        self.dry_run = False
        self.current_action = ""
        self.process: asyncio.subprocess.Process | None = None
        self.log_path: Path | None = None
        self.event_path: Path | None = None
        self.event_offset = 0

        self.status_view = FormattedTextControl(self._render_status)
        self.log_view = TextArea(
            text="No job has run. Logs will appear here.",
            height=Dimension(preferred=11, min=5),
            multiline=True,
            read_only=True,
            focusable=True,
            scrollbar=True,
            wrap_lines=False,
        )
        buttons = [
            Button("Doctor", handler=lambda: self.start("doctor"), width=12),
            Button("Preflight", handler=lambda: self.start("preflight"), width=12),
            Button("Install", handler=lambda: self.start("install"), width=12),
            Button("Upgrade", handler=lambda: self.start("upgrade"), width=12),
        ]
        self.preview_button = Button("Dry-run OFF", handler=self.toggle_dry_run, width=16)
        more_buttons = [
            self.preview_button,
            Button("Update code", handler=lambda: self.start("update"), width=15),
            Button("Full log", handler=self.show_full_log, width=12),
            Button("Quit", handler=self.quit, width=10),
        ]
        kb = KeyBindings()
        @kb.add("c-q")
        def _quit(_event) -> None:
            self.quit()
        @kb.add("f2")
        def _full_log(_event) -> None:
            self.show_full_log()

        body = HSplit(
            [
                Label(" Devbox Bootstrap | Ubuntu developer tools", style="class:header"),
                VSplit(
                    [
                        Frame(self.selector, title="Components [Space to select]", width=Dimension(weight=3)),
                        Frame(
                            Window(content=self.status_view, wrap_lines=False, height=Dimension(min=13)),
                            title="Task status",
                            width=Dimension(weight=2),
                        ),
                    ],
                    padding=1,
                    height=Dimension(weight=3, min=16),
                ),
                Frame(self.log_view, title="Recent output (full log saved to disk)", height=Dimension(weight=2, min=8)),
                VSplit(buttons, padding=1),
                VSplit(more_buttons, padding=1),
                Label(lambda: f" {self.message}", style="class:footer"),
                Label(" Tab: navigate | Space: select | F2: full log | Ctrl-Q: quit", style="class:hint"),
            ]
        )
        self.app = Application(
            layout=Layout(body, focused_element=self.selector),
            key_bindings=kb,
            full_screen=True,
            mouse_support=False,
            style=Style.from_dict(
                {
                    "header": "bold reverse",
                    "footer": "bold",
                    "hint": "fg:ansibrightblack",
                    "frame.border": "fg:ansiblue",
                    "button.focused": "bold reverse",
                }
            ),
        )

    def _render_status(self) -> str:
        rows = [f"  {self.current_action or 'Idle'}", ""]
        for code, _ in COMPONENTS:
            rows.append(f"  {code:<15} {self.status[code]}")
        return "\n".join(rows)

    def _notice(self, message: str) -> None:
        self.message = message
        self.app.invalidate()

    def toggle_dry_run(self) -> None:
        if self.busy:
            self._notice("Dry-run cannot change while an operation is running.")
            return
        self.dry_run = not self.dry_run
        self.preview_button.text = "Dry-run ON" if self.dry_run else "Dry-run OFF"
        self._notice("Dry-run ON: selected install/upgrade steps will be previewed." if self.dry_run else "Dry-run OFF: selected steps will execute.")

    def start(self, action: str) -> None:
        if self.busy:
            self._notice("A task is already running; please finish it first.")
            return
        chosen = list(self.selector.current_values)
        try:
            cmd = build_command(action, chosen, dry_run=self.dry_run)
        except ValueError as exc:
            self._notice(str(exc))
            return
        asyncio.create_task(self._run(action, cmd, chosen))

    async def _authorize_sudo(self) -> bool:
        if not shutil.which("sudo"):
            self._notice("sudo is missing; install/upgrade requires sudo.")
            return False
        self._notice("Authenticating sudo: the terminal prompt will be shown temporarily.")
        # Suspend the full-screen UI while sudo reads from the real TTY.
        async with in_terminal():
            process = await asyncio.create_subprocess_exec("sudo", "-v")
            code = await process.wait()
        if code != 0:
            self._notice("sudo authentication failed or was cancelled.")
            return False
        return True

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
                self._notice("sudo session expired. A privileged step may fail; check the log.")
                return

    async def _run(self, action: str, command: list[str], selected: list[str]) -> None:
        self.busy = True
        self.current_action = action.title()
        self.status = {code: "--" for code, _ in COMPONENTS}
        for item in selected:
            self.status[item] = "QUEUED"
        self._notice(f"Preparing {action}{" (dry-run)" if self.dry_run and action in {"install", "upgrade"} else ""}...")
        keepalive: asyncio.Task[None] | None = None
        try:
            if action in {"install", "upgrade"} and not self.dry_run:
                if not await self._authorize_sudo():
                    return
                keepalive = asyncio.create_task(self._sudo_keepalive())

            log_dir = STATE_ROOT / "logs"
            event_dir = STATE_ROOT / "runs"
            log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            event_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            descriptor, log_name = tempfile.mkstemp(prefix=f"{stamp}-{action}-", suffix=".log", dir=log_dir)
            self.log_path = Path(log_name)
            event_fd, event_name = tempfile.mkstemp(prefix=f"{stamp}-{action}-", suffix=".events", dir=event_dir)
            os.close(event_fd)
            self.event_path = Path(event_name)
            self.event_offset = 0
            env = os.environ.copy()
            env["DEVBOX_EVENT_FILE"] = str(self.event_path)
            with os.fdopen(descriptor, "wb", buffering=0) as log_stream:
                self.process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=ROOT,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self._notice(f"{action.title()} running; log: {self.log_path}")
                while self.process.returncode is None:
                    await asyncio.sleep(0.35)
                    self._refresh()

                code = await self.process.wait()
            self._refresh()
            if code == 0:
                self._notice(f"{action.title()} completed. Full log: {self.log_path}")
            else:
                self._notice(f"{action.title()} FAILED (exit {code}); view full log: {self.log_path}")
                for component in selected:
                    if self.status.get(component) in {"RUNNING", "QUEUED"}:
                        self.status[component] = "FAILED" if self.status[component] == "RUNNING" else "NOT_RUN"
            if action == "update" and code == 0:
                self._notice("Devbox source updated; exit and restart the TUI to load new code.")
        except Exception as exc:
            self._notice(f"Cannot run {action}: {exc}")
        finally:
            if keepalive is not None:
                keepalive.cancel()
                try:
                    await keepalive
                except asyncio.CancelledError:
                    pass
            self.process = None
            self.busy = False
            self.app.invalidate()

    def _refresh(self) -> None:
        events, self.event_offset = read_events(self.event_path, self.event_offset)
        for name, state in events:
            if name in self.status:
                self.status[name] = state
        self.log_view.text = log_tail(self.log_path)
        self.app.invalidate()

    def show_full_log(self) -> None:
        if self.log_path is None:
            self._notice("No log file exists yet.")
            return
        if self.busy:
            self._notice("Full log opens after the active task finishes.")
            return
        asyncio.create_task(self._pager())

    async def _pager(self) -> None:
        async with in_terminal():
            pager = shutil.which("less")
            if pager:
                process = await asyncio.create_subprocess_exec(pager, "-R", "+G", str(self.log_path))
            else:
                process = await asyncio.create_subprocess_exec("tail", "-n", "150", str(self.log_path))
            await process.wait()

    def quit(self) -> None:
        if self.busy:
            self._notice("A task is still active. Closing is disabled to avoid orphaned installers.")
            return
        self.app.exit()

    def run(self) -> None:
        asyncio.run(self.app.run_async())


def main() -> None:
    DevboxTUI().run()


if __name__ == "__main__":
    main()
