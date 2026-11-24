"""Read-only, bounded ownership/version metadata for the component detail pane."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess

from tui.catalog import BINS

APT = {"zsh": ("zsh",), "keychain": ("keychain",), "zoxide": ("zoxide",),
       "fzf": ("fzf",), "ripgrep": ("ripgrep",), "bat-fd": ("bat", "fd-find"),
       "direnv": ("direnv",), "docker": ("docker-ce", "docker.io"),
       "nvidia": ("nvidia-container-toolkit",), "kubectl": ("kubectl",),
       "minikube": ("minikube",), "uv": ("uv",)}
RECEIPTS = {"kubectl": Path("/usr/local/bin/kubectl"),
            "minikube": Path("/usr/local/bin/minikube")}


def inspect_components():
    result = {}
    packages = {}
    if shutil.which("dpkg-query"):
        try:
            query = subprocess.run(["dpkg-query", "-W", "-f=${Package}\\t${Status}\\t${Version}\\n",
                                    *sorted({p for items in APT.values() for p in items})],
                                   capture_output=True, text=True, timeout=3, check=False,
                                   stdin=subprocess.DEVNULL)
            for line in query.stdout.splitlines():
                fields = line.split("\t")
                if len(fields) == 3 and fields[1] == "install ok installed":
                    packages[fields[0]] = fields[2]
        except (OSError, subprocess.TimeoutExpired):
            pass
    for code, names in BINS.items():
        binary = next((path for name in names if (path := shutil.which(name))), None)
        if not binary:
            continue
        installed = [f"{p} {packages[p]}" for p in APT.get(code, ()) if p in packages]
        if code in RECEIPTS and Path(binary) == RECEIPTS[code]:
            receipt = Path.home() / ".local/state/devbox-bootstrap/managed" / (code + ".sha256")
            try:
                if receipt.is_symlink() or Path(binary).is_symlink() or receipt.stat().st_size > 256:
                    raise OSError("unsafe receipt")
                with open(binary, "rb") as stream:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                owned = digest.hexdigest() == receipt.read_text().strip()
            except OSError:
                owned = False
            source = "Devbox-managed binary" if owned else "External/legacy binary; auto-upgrade blocked"
        elif installed:
            source = "APT installed: " + ", ".join(installed) + "; active executable ownership not verified"
        else:
            source = "Installed; manager/ownership not verified"
        result[code] = f"{binary}\n  {source}"
    return result
