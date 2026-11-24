"""System, storage and project discovery without persistent monitoring."""
from __future__ import annotations

import os
import heapq
import time
import platform
import shutil
from pathlib import Path

from .native import native, bytes_label, existing_dir, local_docker


def host(_value, _cwd):
    usage = shutil.disk_usage(Path.home())
    return (f"OS: {platform.platform()}\nArchitecture: {platform.machine()}\n"
            f"CPU threads: {os.cpu_count()}\nHome filesystem: {bytes_label(usage.used)} used / "
            f"{bytes_label(usage.total)} total\nWSL: {'yes' if 'microsoft' in platform.release().lower() else 'no'}")


def processes(value, _cwd):
    rows = native(["ps", "-eo", "pid,user,pcpu,pmem,comm", "--sort=-pcpu"]).splitlines()
    return "\n".join(rows[:1] + [r for r in rows[1:] if value.casefold() in r.casefold()][:100])


def gpu(_value, _cwd):
    return native(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu", "--format=csv"])


def gpu_processes(_value, _cwd):
    return native(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv"])


def services(_value, _cwd):
    return native(["systemctl", "list-units", "--type=service", "--no-pager", "--plain", "--no-legend"])


def ssh_keys(_value, _cwd):
    # Public key filenames only; never read private key contents.
    root = Path.home() / ".ssh"
    if not root.is_dir():
        return "No ~/.ssh directory"
    return "\n".join(str(p) for p in sorted(root.glob("*.pub")) if p.is_file()) or "No public keys found."


def ssh_agent(_value, _cwd):
    return native(["ssh-add", "-l"])


def path_entries(value, _cwd):
    if value:
        if "/" in value or not value.strip() or any(c.isspace() for c in value):
            raise ValueError("Enter a single executable name.")
        found = []
        for folder in os.get_exec_path():
            path = Path(folder or ".") / value
            if path.is_file() and os.access(path, os.X_OK):
                found.append(str(path.absolute()))
        return "\n".join(found) or "Executable not found."
    return "\n".join(os.get_exec_path())


def storage(_value, _cwd):
    rows = []
    for path in dict.fromkeys((Path("/"), Path.home())):
        usage = shutil.disk_usage(path)
        rows.append(f"{path}: {bytes_label(usage.used)} / {bytes_label(usage.total)}  ({usage.used / max(usage.total, 1):.0%})")
    return "\n".join(rows) + "\nMounts may refer to the same filesystem; do not sum."


def largest(value, cwd):
    path = existing_dir(value, cwd)
    if path == Path("/"):
        raise ValueError("Choose a specific directory, not the entire root filesystem.")
    # GNU du does not follow symlinks by default. Bound traversal time and output.
    output = native(["du", "-x", "-B1", "--max-depth=1", "--", str(path)], timeout=15)
    rows = []
    for line in output.splitlines():
        size, sep, label = line.partition("\t")
        if sep and size.isdigit() and label != str(path):
            rows.append((int(size), label))
    return "\n".join(f"{bytes_label(size):>12}  {label}" for size, label in sorted(rows, reverse=True)[:30]) or "No measurable subdirectories."


def cache_locations():
    home = Path.home()
    return [("pip", home / ".cache/pip"), ("uv", home / ".cache/uv"),
             ("npm", home / ".npm"), ("pnpm", home / ".local/share/pnpm/store"),
             ("Yarn", home / ".cache/yarn"), ("Hugging Face", Path(os.environ.get("HF_HOME") or home / ".cache/huggingface")),
             ("PyTorch", home / ".cache/torch"), ("Ollama", Path(os.environ.get("OLLAMA_MODELS") or home / ".ollama/models"))]


def caches(_value, _cwd):
    paths = cache_locations()
    return "\n".join(f"{name:<14} {'Present' if path.is_dir() else 'Not found':<10} {path}" for name, path in paths) + "\nLocation hints only; no cache or model is deleted."


def containers(_value, cwd):
    return local_docker(["ps", "-a", "--format", "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"], cwd)


def docker_disk(_value, cwd):
    return local_docker(["system", "df"], cwd)


def container_logs(value, cwd):
    if not value or value.startswith("-") or not all(c.isalnum() or c in "_.-" for c in value):
        raise ValueError("Enter a container name or ID.")
    return local_docker(["logs", "--tail", "100", value], cwd)


def compose(_value, cwd):
    return local_docker(["compose", "ps", "-a"], cwd)


PROJECT_MARKERS = (".git", "pyproject.toml", "uv.lock", "package.json", "compose.yaml",
                   "compose.yml", "docker-compose.yml", "Makefile", "justfile", ".mise.toml", "AGENTS.md")


def project(_value, cwd):
    path = Path(cwd)
    found = [name for name in PROJECT_MARKERS if (path / name).exists()]
    return str(path) + "\n" + ("\n".join(found) or "No known project markers in this directory.") + "\nDetection only; project scripts are not executed."


def git_status(_value, cwd):
    return native(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "status",
                   "--short", "--branch", "--untracked-files=no"], cwd=cwd)


def cache_sizes(_value, _cwd):
    from concurrent.futures import ThreadPoolExecutor
    def measure(row):
        name, path = row
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            return f"{name:<14} unavailable"
        try:
            size = int(native(["du", "-sx", "-B1", "--", str(path)], timeout=10).split()[0])
            return f"{name:<14} {bytes_label(size):>12}  {path}"
        except (OSError, ValueError, RuntimeError):
            return f"{name:<14} unknown  {path}"
    with ThreadPoolExecutor(max_workers=3) as pool:
        return "\n".join(pool.map(measure, cache_locations())) + "\nFootprints may overlap; no data is deleted."


def largest_files(value, cwd):
    import stat
    root = existing_dir(value, cwd)
    if root == Path("/"):
        raise ValueError("Choose a specific directory, not the entire root filesystem.")
    device = root.stat().st_dev
    stack = [root]
    heap = []
    visited = 0
    deadline = time.monotonic() + 8
    partial = False
    while stack and not partial:
        directory = stack.pop()
        try:
            with os.scandir(directory) as rows:
                for entry in rows:
                    visited += 1
                    if visited > 100000 or time.monotonic() > deadline:
                        partial = True
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if info.st_dev != device:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            stack.append(entry.path)
                        elif stat.S_ISREG(info.st_mode):
                            row = (info.st_size, entry.path)
                            if len(heap) < 30:
                                heapq.heappush(heap, row)
                            else:
                                heapq.heappushpop(heap, row)
                    except OSError:
                        continue
        except OSError:
            continue
    output = "\n".join(f"{bytes_label(size):>12}  {path}" for size, path in sorted(heap, reverse=True))
    return (output or "No readable files.") + ("\nPartial results: scan budget reached." if partial else "\nLogical file sizes; inaccessible paths and other filesystems excluded.")
