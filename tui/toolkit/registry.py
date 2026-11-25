"""Shared action registry. No discovery or native commands during import/render."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import agents, data, network, system, environment, health
from .guidance import GUIDES, Guide

@dataclass(frozen=True)
class Action:
    id: str
    label: str
    category: str
    handler: Callable[[str, str], str]
    description: str
    prompt: str = ""
    required: bool = False
    sensitive: bool = False
    mode: str = "query"

    @property
    def guide(self) -> Guide:
        return GUIDES[self.id]


ACTIONS = (
    Action("health.check", "Structured health report", "Health", health.report, "Run bounded local diagnostics."),
    Action("health.json", "Health report JSON", "Health", health.report_json, "Machine-readable diagnostic evidence."),
    Action("env.list", "Development tool inventory", "Environment", environment.tools, "Inspect detected tools and ownership evidence."),
    Action("env.profile", "Preview desired-state profile", "Environment", environment.profile_plan, "Review a JSON profile without applying changes.", "Profile file", True),
    Action("net.ports", "Listening ports", "Networking", network.ports, "List local TCP/UDP listeners."),
    Action("net.port", "Find process by port", "Networking", network.port, "Inspect listeners on an exact port.", "Port", True),
    Action("net.ip", "Local IP addresses", "Networking", network.addresses, "Show interface addresses."),
    Action("net.routes", "IP routing", "Networking", network.routes, "Show local routing table."),
    Action("net.dns", "DNS lookup", "Networking", network.dns, "Resolve a hostname.", "Hostname", True),
    Action("net.tcp", "TCP connectivity", "Networking", network.tcp, "Connect to a chosen host and port.", "host:port", True),
    Action("net.http", "HTTP status and timing", "Networking", network.http, "Explicit HEAD request; no redirects or body.", "HTTP(S) URL", True, True),
    Action("net.tls", "TLS certificate", "Networking", network.tls, "Inspect a verified TLS connection.", "host[:port]", True),
    Action("sys.host", "Host information", "System", system.host, "OS, CPU, WSL and home filesystem."),
    Action("sys.processes", "Find processes", "System", system.processes, "List processes by CPU without command arguments.", "Optional name"),
    Action("sys.gpu", "GPU information", "System", system.gpu, "GPU memory, temperature and utilization."),
    Action("sys.gpu-processes", "GPU processes", "System", system.gpu_processes, "GPU compute process memory."),
    Action("sys.services", "System services", "System", system.services, "List systemd services."),
    Action("sys.ssh-keys", "SSH public keys", "System", system.ssh_keys, "List public key files only."),
    Action("sys.ssh-agent", "SSH agent", "System", system.ssh_agent, "List loaded key fingerprints."),
    Action("sys.path", "Inspect PATH", "System", system.path_entries, "Show PATH or matching executable paths.", "Optional executable"),
    Action("storage.usage", "Filesystem usage", "Storage", system.storage, "Root and home filesystem usage."),
    Action("storage.largest", "Largest directories", "Storage", system.largest, "Explicit scoped, read-only directory scan.", "Directory (default: current project)"),
    Action("storage.files", "Largest files", "Storage", system.largest_files, "Bounded, read-only scan of a selected directory.", "Directory (default: current project)"),
    Action("storage.cache-sizes", "Measure developer caches", "Storage", system.cache_sizes, "Explicit measurement of common cache footprints."),
    Action("storage.caches", "Developer / AI cache locations", "Storage", system.caches, "Inspect known cache locations; no deletion."),
    Action("docker.ps", "Containers and ports", "Containers", system.containers, "List local Docker containers."),
    Action("docker.disk", "Docker storage", "Containers", system.docker_disk, "Docker disk inventory."),
    Action("docker.logs", "Container log tail", "Containers", system.container_logs, "Last 100 lines; never recorded by Devbox.", "Container name or ID", True, True),
    Action("docker.compose", "Compose project status", "Containers", system.compose, "Inspect Compose services in current directory."),
    Action("agent.list", "Coding agent CLIs", "Coding Agents", agents.agent_list, "Discover agent executable paths."),
    Action("agent.integrations", "Integration matrix", "Coding Agents", agents.matrix, "RTK and Ponytail registration evidence."),
    Action("agent.version", "Agent CLI version", "Coding Agents", agents.version, "Read the version of one agent CLI.", "Agent ID", True),
    Action("agent.skill-updates", "Check skill updates", "Coding Agents", agents.skill_updates, "Explicit network update check via Skills CLI."),
    Action("agent.skills", "Installed skills", "Coding Agents", agents.skills, "List via official Skills CLI.", "global (default) / project"),
    Action("project.detect", "Detect project", "Project", system.project, "Discover project markers without execution."),
    Action("project.git", "Git status", "Project", system.git_status, "Read working-tree and branch status."),
    Action("util.json-format", "Format JSON", "Utilities", data.json_format, "Pretty-print JSON locally.", "JSON", True, True, "instant"),
    Action("util.json-minify", "Minify JSON", "Utilities", data.json_minify, "Compact JSON locally.", "JSON", True, True, "instant"),
    Action("util.base64-encode", "Base64 encode", "Utilities", data.b64encode, "Encode UTF-8 text.", "Text", True, True, "instant"),
    Action("util.base64-decode", "Base64 decode", "Utilities", data.b64decode, "Decode Base64 to UTF-8.", "Base64", True, True, "instant"),
    Action("util.url-encode", "URL encode", "Utilities", data.url_encode, "Percent-encode text.", "Text", True, True, "instant"),
    Action("util.url-decode", "URL decode", "Utilities", data.url_decode, "Decode percent escapes.", "Text", True, True, "instant"),
    Action("util.uuid", "Generate UUID v4", "Utilities", data.uuid4, "Random UUID.", mode="instant"),
    Action("util.uuid7", "Generate UUID v7", "Utilities", data.uuid7, "Time-ordered UUID.", mode="instant"),
    Action("util.token", "Generate secure token", "Utilities", data.token, "Random URL-safe token; never persisted.", sensitive=True, mode="instant"),
    Action("util.jwt", "Inspect JWT", "Utilities", data.jwt, "Decode only; does not verify signatures.", "JWT", True, True, "instant"),
    Action("util.timestamp", "Unix timestamp", "Utilities", data.timestamp, "Convert Unix seconds to UTC or show current timestamp.", "Optional Unix seconds", mode="instant"),
    Action("util.sha256", "File SHA-256", "Utilities", data.checksum, "Stream a file to calculate its checksum.", "File path", True),
)
BY_ID = {action.id: action for action in ACTIONS}
CATEGORIES = tuple(dict.fromkeys(action.category for action in ACTIONS))


def execute(action_id: str, value: str, cwd: str) -> str:
    action = BY_ID[action_id]
    if action.required and not value.strip():
        raise ValueError(f"{action.prompt} is required.")
    if len(value.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Input exceeds 1 MiB.")
    return action.handler(value, cwd)
