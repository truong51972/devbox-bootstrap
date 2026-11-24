"""Exact-target convenience mutations; explicit confirmation and shared lock."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal

from tui.operation_lock import operation_lock
from tui.cleaner import docker_prefix, command_env
from .native import native

DOCKER_ID = re.compile(r"^[0-9a-f]{64}$")
DOCKER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class Plan:
    action: str
    target: str
    identity: str
    description: str
    endpoint: str = ""


def process_identity(pid):
    if pid <= 1 or pid == os.getpid() or pid == os.getppid():
        raise ValueError("Refusing a protected process.")
    root = Path("/proc") / str(pid)
    if root.stat().st_uid != os.getuid():
        raise ValueError("Only processes owned by the current user are eligible.")
    stat = (root / "stat").read_text()
    tail = stat.rsplit(")", 1)[1].split()
    # Field 22: process start time since boot, distinguishing reused PIDs.
    return tail[19], (root / "comm").read_text().strip()


def docker_identity(value, cwd, endpoint=""):
    if not DOCKER_NAME.fullmatch(value):
        raise ValueError("Enter an exact container name or ID.")
    prefix = docker_prefix()
    if endpoint and prefix[-1] != endpoint:
        raise ValueError("Docker endpoint changed; create a new plan.")
    cmd = prefix + ["container", "inspect", "--format", "{{.Id}}", value]
    identity = native(cmd, cwd=cwd, env=command_env(cmd))
    if not DOCKER_ID.fullmatch(identity):
        raise ValueError("Could not verify an exact container ID.")
    return identity, prefix[-1]


def prepare(action, target, cwd):
    if action == "sys.terminate":
        if not target.isascii() or not target.isdigit():
            raise ValueError("Enter a numeric PID.")
        pid = int(target)
        identity, name = process_identity(pid)
        return Plan(action, str(pid), identity, f"Send SIGTERM to PID {pid} ({name}).")
    if action in ("docker.start", "docker.stop", "docker.restart"):
        identity, endpoint = docker_identity(target, cwd)
        verb = action.split(".")[1]
        return Plan(action, target, identity, f"{verb.title()} container {target} ({identity[:12]}) on {endpoint}.", endpoint)
    raise ValueError("Unknown managed action.")


def apply(plan, cwd):
    with operation_lock():
        if plan.action == "sys.terminate":
            pid = int(plan.target)
            if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
                raise ValueError("Safe PID handles are unavailable on this kernel/Python.")
            fd = os.pidfd_open(pid)
            try:
                identity, _ = process_identity(pid)
                if identity != plan.identity:
                    raise ValueError("PID changed; create a new plan.")
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
            return "SIGTERM sent; termination is not guaranteed."
        identity, endpoint = docker_identity(plan.target, cwd, plan.endpoint)
        if identity != plan.identity:
            raise ValueError("Container identity changed; create a new plan.")
        cmd = ["docker", "--host", endpoint, "container", plan.action.split(".")[1], identity]
        return native(cmd, cwd=cwd, env=command_env(cmd), timeout=45)
