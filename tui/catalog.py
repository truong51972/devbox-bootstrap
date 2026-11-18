"""Component catalog and read-only host inventory."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from tui.agent_status import probe_ponytail, summary as ponytail_summary

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
    ("rtk", "RTK (token optimizer)"),
    ("skills-cli", "Skills CLI"),
    ("ponytail", "Ponytail (agent plugin)"),
)
GROUPS = (
    ("SHELL", ("zsh", "powerlevel10k", "keychain")),
    ("DEVELOPER TOOLS", ("uv", "zoxide", "fzf", "ripgrep", "bat-fd", "direnv")),
    ("CONTAINERS", ("docker", "nvidia")),
    ("KUBERNETES", ("kubectl", "minikube")),
    ("AI AGENT EXTENSIONS", ("rtk", "skills-cli", "ponytail")),
)
DEPENDENCIES = {"powerlevel10k": ("zsh",), "nvidia": ("docker",)}
BINS = {
    "zsh": ("zsh",), "uv": ("uv",), "keychain": ("keychain",),
    "zoxide": ("zoxide",), "fzf": ("fzf",), "ripgrep": ("rg",),
    "bat-fd": ("bat", "batcat"), "docker": ("docker",),
    "nvidia": ("nvidia-ctk",), "kubectl": ("kubectl",),
    "minikube": ("minikube",), "direnv": ("direnv",),
    "rtk": ("rtk",), "skills-cli": ("skills",),
}
ORDER = tuple(code for code, _ in COMPONENTS)


def executable(name: str) -> bool:
    home = Path.home()
    return bool(shutil.which(name) or any(
        (home / sub / name).is_file()
        for sub in (".local/bin", ".cargo/bin")
    ))


def installed(code: str) -> bool:
    if code == "ponytail":
        # A recorded install is not proof the agent plugin is still enabled.
        return False
    if code == "powerlevel10k":
        return (Path.home() / "powerlevel10k/powerlevel10k.zsh-theme").is_file()
    if code == "rtk":
        executable_path = shutil.which("rtk") or str(Path.home() / ".local/bin/rtk")
        try:
            return subprocess.run([executable_path, "gain"], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=2).returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
    if code == "bat-fd":
        return (executable("bat") or executable("batcat")) and (
            executable("fd") or executable("fdfind")
        )
    return any(executable(name) for name in BINS.get(code, ()))


def inventory(ponytail_agents: dict[str, str] | None = None) -> dict[str, str]:
    """Availability; Ponytail checks agent inventories rather than receipts alone."""
    result = {code: "Installed" if installed(code) else "Missing" for code in ORDER}
    states = probe_ponytail() if ponytail_agents is None else ponytail_agents
    result["ponytail"] = ponytail_summary(states)
    return result


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
