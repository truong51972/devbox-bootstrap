"""Local run artifacts and subprocess lifecycle; no forced cancellation of APT."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile


@dataclass
class RunFiles:
    log: Path
    events: Path
    fd: int


def prepare_run(state_root: Path, action: str) -> RunFiles:
    logs, events = state_root / "logs", state_root / "runs"
    for directory in (logs, events):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fd, name = tempfile.mkstemp(prefix=f"{stamp}-{action}-", suffix=".log", dir=logs)
    try:
        event_fd, event_name = tempfile.mkstemp(prefix=f"{stamp}-{action}-", suffix=".events", dir=events)
        os.close(event_fd)
    except BaseException:
        os.close(fd)
        Path(name).unlink(missing_ok=True)
        raise
    return RunFiles(Path(name), Path(event_name), fd)


def run_env(event_path: Path, enabled: set[str]) -> dict[str, str]:
    env = dict(os.environ, DEVBOX_EVENT_FILE=str(event_path), DEVBOX_TUI_MODE="1")
    for key, option in (
        ("DEVBOX_CONFIRM_CHANGE_SHELL", "change_shell"),
        ("DEVBOX_CONFIRM_DOCKER_GROUP", "docker_group"),
        ("DEVBOX_CONFIRM_SSH_KEY", "ssh_key"),
        ("DEVBOX_CONFIRM_KUBECTL_REPLACE", "kubectl_replace"),
    ):
        env[key] = "yes" if option in enabled else "no"
    return env


async def launch(command, *, root, env, output):
    return await asyncio.create_subprocess_exec(
        *command, cwd=root, env=env, stdin=subprocess.DEVNULL,
        stdout=output, stderr=subprocess.STDOUT,
    )


async def wait_for_run(process, refresh, *, interval=0.3):
    # Navigation cannot cancel this operation. If the controller itself is
    # cancelled, wait for the native child instead of terminating APT midway.
    waiter = asyncio.create_task(process.wait())
    try:
        while not waiter.done():
            await asyncio.wait({waiter}, timeout=interval)
            refresh()
        return waiter.result()
    except asyncio.CancelledError:
        await asyncio.shield(waiter)
        raise
    except Exception:
        # A log reader failure must not leave a mutating child orphaned.
        await asyncio.shield(waiter)
        raise
