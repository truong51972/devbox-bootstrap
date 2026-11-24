"""Bounded, noninteractive Git update discovery for the TUI."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import signal

ORIGINS = {
    "https://github.com/truong51972/devbox-bootstrap.git",
    "https://github.com/truong51972/devbox-bootstrap",
    "git@github.com:truong51972/devbox-bootstrap.git",
}
CHECK_TIMEOUT = 12


@dataclass(frozen=True)
class UpdateCheck:
    state: str
    current: str = ""
    latest: str = ""
    commits: int = 0


async def git(root: Path, *args: str) -> tuple[int, str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(root), *args,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=env, start_new_session=True,
    )
    try:
        output, _ = await process.communicate()
    except asyncio.CancelledError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.communicate()
        raise
    return process.returncode, output.decode(errors="replace").strip()


async def _check(root: Path) -> UpdateCheck:
    async def read(*args: str) -> str:
        code, output = await git(root, *args)
        if code:
            raise RuntimeError("Git check failed")
        return output

    if await read("remote", "get-url", "origin") not in ORIGINS:
        return UpdateCheck("unsupported")
    if await read("symbolic-ref", "--quiet", "--short", "HEAD") != "main":
        return UpdateCheck("unsupported")
    if await read("status", "--porcelain", "--untracked-files=no"):
        return UpdateCheck("dirty")
    current = await read("rev-parse", "HEAD")
    # Fetch objects only, never merge or modify source. Use the fetched ref
    # for ancestry validation; ahead/diverged checkouts must not be offered.
    await read("fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
               "origin", "+refs/heads/main:refs/devbox/update-check")
    latest = await read("rev-parse", "refs/devbox/update-check")
    if current == latest:
        return UpdateCheck("current", current, latest)
    code, _ = await git(root, "merge-base", "--is-ancestor", current, latest)
    if code == 1:
        return UpdateCheck("not-fast-forward", current, latest)
    if code:
        raise RuntimeError("Git ancestry check failed")
    commits = int(await read("rev-list", "--count", f"{current}..{latest}"))
    return UpdateCheck("available", current, latest, commits)


async def check_update(root: Path) -> UpdateCheck:
    try:
        return await asyncio.wait_for(_check(root), timeout=CHECK_TIMEOUT)
    except (OSError, RuntimeError, ValueError, asyncio.TimeoutError):
        return UpdateCheck("unavailable")
