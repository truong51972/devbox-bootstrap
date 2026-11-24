"""Explicitly invoked local workflow launcher.

Custom commands live in the user's configuration directory, never in an
untrusted repository. No shell evaluation or automatic execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

from .settings import config_dir, read_json


@dataclass(frozen=True)
class Workflow:
    id: str
    command: tuple[str, ...]
    description: str
    custom: bool = False


BUILTINS = (
    Workflow("gpu-watch", ("watch", "-n", "1", "nvidia-smi"), "Live NVIDIA GPU status"),
    Workflow("btop", ("btop",), "System monitoring"),
    Workflow("lazydocker", ("lazydocker",), "Interactive Docker management"),
    Workflow("lazygit", ("lazygit",), "Interactive Git management"),
)


def list_workflows():
    result = {w.id: w for w in BUILTINS}
    path = config_dir() / "actions.json"
    if not path.exists():
        return result
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError("actions.json must be a list of workflows.")
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Invalid workflow.")
        key, argv = row.get("id"), row.get("command")
        if (not isinstance(key, str) or not key or not key.isascii() or not all(c.isalnum() or c in "-_" for c in key)
                or key in result or not isinstance(argv, list) or not argv
                or any(not isinstance(v, str) or "\0" in v for v in argv)):
            raise ValueError("Invalid or duplicate workflow.")
        result[key] = Workflow(key, tuple(argv), "User-defined command", True)
    return result


def run(workflow, cwd):
    if not shutil.which(workflow.command[0]):
        raise ValueError("Executable not available: " + workflow.command[0])
    return subprocess.call(workflow.command, cwd=cwd)
