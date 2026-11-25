"""Explicitly adopt only official legacy kubectl/Minikube release binaries."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

KEYS = frozenset(("kubectl", "minikube"))
VERSION = re.compile(r"\d+\.\d+\.\d+")
SHA256 = re.compile(r"[0-9a-f]{64}")


def eligible(key, path):
    if key not in KEYS or path != "/usr/local/bin/" + key:
        return False
    try:
        info = Path(path).lstat()
        return stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
    except OSError:
        return False


def output(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=15).strip()


def digest(path):
    with path.open("rb") as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()


def adopt(key, version):
    if key not in KEYS or not VERSION.fullmatch(version):
        raise ValueError("Unsupported binary or release version.")
    active = shutil.which(key)
    if not eligible(key, active):
        raise ValueError("Only root-owned, non-writable official-path regular binaries may be adopted.")
    path = Path(active)
    from .resources import binary_version
    if binary_version(key, active) != version:
        raise ValueError("Installed version changed; review again.")
    # Never take over an APT package or a symlink, even with a matching digest.
    for query in (active, str(path.resolve())):
        result = subprocess.run(["dpkg-query", "-S", query], capture_output=True, timeout=5, check=False)
        if result.returncode != 1:
            raise ValueError("Package ownership present or cannot be checked.")
    arch = output("dpkg", "--print-architecture")
    if arch not in ("amd64", "arm64"):
        raise ValueError("Unsupported architecture.")
    url = ("https://dl.k8s.io/release/v" + version + "/bin/linux/" + arch + "/kubectl.sha256"
           if key == "kubectl" else
           "https://github.com/kubernetes/minikube/releases/download/v" + version + "/minikube-linux-" + arch + ".sha256")
    expected = output("curl", "-fsSL", "--max-time", "10", url)
    if not SHA256.fullmatch(expected) or digest(path) != expected:
        raise ValueError("Official release checksum mismatch; binary preserved.")
    state = Path.home() / ".local/state/devbox-bootstrap/managed"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt = state / (key + ".sha256")
    if state.is_symlink() or receipt.is_symlink() or (receipt.exists() and not receipt.is_file()):
        raise ValueError("Unsafe ownership receipt path.")
    # Revalidate exact target and content immediately before atomic receipt write.
    if shutil.which(key) != active or not eligible(key, active) or digest(path) != expected:
        raise ValueError("Binary changed during adoption.")
    with tempfile.NamedTemporaryFile(mode="w", dir=state, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(expected + "\n")
    try:
        os.replace(temporary, receipt)
    finally:
        temporary.unlink(missing_ok=True)
    print(key + " adopted; binary unchanged. Refresh inventory to enable safe updates.")


def main():
    if len(sys.argv) != 3 or os.geteuid() == 0:
        return 2
    try:
        adopt(sys.argv[1], sys.argv[2])
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Adoption refused: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
