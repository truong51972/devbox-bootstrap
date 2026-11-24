"""Shared per-user advisory lock, compatible with Bash flock."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


@contextmanager
def operation_lock():
    state = Path.home() / ".local/state/devbox-bootstrap"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(state / "operation.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError("Unsafe Devbox operation lock path")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another Devbox operation is running. Try again after it completes.") from exc
        yield
    finally:
        os.close(fd)
