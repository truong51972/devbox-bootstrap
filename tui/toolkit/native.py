"""Bounded, shell-free native queries; never write operation logs."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_OUTPUT = 128 * 1024
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def safe_text(value: str) -> str:
    value = ANSI.sub("", value)
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127 and not 128 <= ord(c) <= 159))


def native(argv, *, cwd=None, timeout=8, env=None):
    """Capture bounded output from a finite native query; fail on nonzero exit."""
    # Resolve before changing cwd; ignore relative PATH entries for discovery.
    trusted_path = os.pathsep.join(p for p in os.get_exec_path(env) if os.path.isabs(p))
    binary = shutil.which(argv[0], path=trusted_path) if argv and trusted_path else None
    if not binary or not os.path.isabs(binary):
        raise ValueError("Required executable unavailable: " + (argv[0] if argv else "?"))
    with tempfile.TemporaryFile() as out:
        try:
            result = subprocess.run([binary, *argv[1:]], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Command timed out.") from exc
        out.seek(0)
        raw = out.read(MAX_OUTPUT + 1)
    value = safe_text(raw[:MAX_OUTPUT].decode("utf-8", errors="replace"))
    if len(raw) > MAX_OUTPUT:
        value += "\n[Output truncated]"
    if result.returncode:
        raise ValueError(f"Command exited {result.returncode}: {value.strip()[:2000]}")
    return value.strip() or "(no output)"


def bytes_label(value):
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(amount) < 1024 or unit == "PiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024


def existing_dir(value, cwd):
    path = Path(value or cwd).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Select an existing directory.")
    return path


def local_docker(args, cwd=None):
    # Reuse Cleaner endpoint guard, including Docker context precedence.
    from tui.cleaner import docker_prefix, command_env
    prefix = docker_prefix()
    argv = prefix + list(args)
    return native(argv, cwd=cwd, env=command_env(argv), timeout=12)
