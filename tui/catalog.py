"""Component catalog and read-only host inventory."""
from __future__ import annotations

from pathlib import Path
import shutil

COMPONENTS = (
    ("zsh", "Zsh + Oh My Zsh"),
    ("powerlevel10k", "Powerlevel10k"),
    ("uv", "uv (Python)"),
    ("keychain", "SSH keychain"),
    ("zoxide", "zoxide"),
    ("fzf", "fzf"),
    ("ripgrep", "ripgrep"),
    ("bat-fd", "bat + fd"),
    ("docker", "Docker Engine"),
    ("nvidia", "NVIDIA Container Toolkit"),
    ("kubectl", "kubectl"),
    ("minikube", "Minikube"),
    ("direnv", "direnv"),
)
GROUPS = (
    ("SHELL", ("zsh", "powerlevel10k", "keychain")),
    ("DEVELOPER TOOLS", ("uv", "zoxide", "fzf", "ripgrep", "bat-fd", "direnv")),
    ("CONTAINERS", ("docker", "nvidia")),
    ("KUBERNETES", ("kubectl", "minikube")),
)
DEPENDENCIES = {"powerlevel10k": ("zsh",), "nvidia": ("docker",)}
BINS = {
    "zsh": ("zsh",), "uv": ("uv",), "keychain": ("keychain",),
    "zoxide": ("zoxide",), "fzf": ("fzf",), "ripgrep": ("rg",),
    "bat-fd": ("bat", "batcat"), "docker": ("docker",),
    "nvidia": ("nvidia-ctk",), "kubectl": ("kubectl",),
    "minikube": ("minikube",), "direnv": ("direnv",),
}
ORDER = tuple(code for code, _ in COMPONENTS)


def executable(name: str) -> bool:
    home = Path.home()
    return bool(shutil.which(name) or any(
        (home / sub / name).is_file()
        for sub in (".local/bin", ".cargo/bin")
    ))


def installed(code: str) -> bool:
    if code == "powerlevel10k":
        return (Path.home() / "powerlevel10k/powerlevel10k.zsh-theme").is_file()
    if code == "bat-fd":
        return (executable("bat") or executable("batcat")) and (
            executable("fd") or executable("fdfind")
        )
    return any(executable(name) for name in BINS.get(code, ()))


def inventory() -> dict[str, str]:
    """Availability, not a guarantee that a daemon or shell hook is healthy."""
    return {code: "Installed" if installed(code) else "Missing" for code in ORDER}


def with_dependencies(selected: list[str], present: dict[str, str]) -> tuple[list[str], list[str]]:
    """Include missing prerequisites, retaining the Bash install order."""
    requested = set(selected)
    if requested - set(ORDER):
        raise ValueError("Unknown component selected.")
    extra: set[str] = set()
    for code in tuple(requested):
        for dependency in DEPENDENCIES.get(code, ()):
            if dependency not in requested and present.get(dependency) != "Installed":
                requested.add(dependency)
                extra.add(dependency)
    return [code for code in ORDER if code in requested], [
        code for code in ORDER if code in extra
    ]
