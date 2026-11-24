"""Structured, read-only diagnostic checks."""
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
from .native import native, local_docker

CHECKS = (
    ("docker", "Docker daemon", "docker", lambda: local_docker(["info", "--format", "{{.ServerVersion}}"])),
    ("compose", "Docker Compose", "docker", lambda: native(["docker", "compose", "version"])),
    ("gpu", "NVIDIA GPU", "nvidia-smi", lambda: native(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])),
    ("kubectl", "Kubernetes client", "kubectl", lambda: native(["kubectl", "version", "--client"])),
    ("python", "Python runtime", "python3", lambda: native(["python3", "--version"])),
    ("git", "Git executable", "git", lambda: native(["git", "--version"])),
)

def collect():
    def check(spec):
        key, label, executable, fn = spec
        row = {"id": key, "label": label}
        if not shutil.which(executable):
            return dict(row, status="Unavailable", evidence="Optional executable not detected.")
        try:
            evidence = fn()
            return dict(row, status="Passed", evidence=evidence[:2000])
        except (ValueError, RuntimeError, OSError) as exc:
            return dict(row, status="Warning", evidence=str(exc)[:2000],
                        recommendation="Inspect the executable or native service; no automatic repair.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(check, CHECKS))

def report(_value, _cwd):
    return "\n".join(f"{r['status']:<12} {r['label']}\n  {r['evidence']}" for r in collect())

def report_json(_value, _cwd):
    return json.dumps({"schema": 1, "checks": collect()}, indent=2)
