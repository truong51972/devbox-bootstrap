"""Action guidance, input kinds and related actions. No runtime I/O."""
from dataclasses import dataclass
import shlex

@dataclass(frozen=True)
class Guide:
    group: str
    kind: str
    example: str
    use: str
    result: str
    limit: str
    related: tuple[str, ...]

_DATA = {
  "health.check": {
    "group": "Diagnostics",
    "kind": "none",
    "example": "",
    "use": "Check development prerequisites.",
    "result": "Individual check states and evidence.",
    "limit": "No automatic repair.",
    "related": [
      "health.json"
    ]
  },
  "health.json": {
    "group": "Diagnostics",
    "kind": "none",
    "example": "",
    "use": "Export diagnostic evidence for automation.",
    "result": "JSON diagnostic document.",
    "limit": "Contains local environment information.",
    "related": [
      "health.check"
    ]
  },
  "env.list": {
    "group": "Tools",
    "kind": "none",
    "example": "",
    "use": "Find missing tools or installation ownership.",
    "result": "Inventory with state, path and evidence.",
    "limit": "Detection does not prove runtime health.",
    "related": [
      "legacy:install",
      "legacy:upgrade"
    ]
  },
  "env.profile": {
    "group": "Profiles",
    "kind": "path",
    "example": "./profile.json",
    "use": "Compare desired state with your workstation.",
    "result": "Missing tools and requested integrations.",
    "limit": "Preview only.",
    "related": [
      "env.list"
    ]
  },
  "net.ports": {
    "group": "Local network",
    "kind": "none",
    "example": "",
    "use": "Find occupied ports before starting a server.",
    "result": "TCP/UDP listeners, addresses and visible process owners.",
    "limit": "PID may be hidden by permissions; local namespace only.",
    "related": [
      "net.port",
      "sys.processes"
    ]
  },
  "net.port": {
    "group": "Local network",
    "kind": "port",
    "example": "8000",
    "use": "A server reports address already in use.",
    "result": "Listeners on the selected port.",
    "limit": "No listener does not prove another namespace is free.",
    "related": [
      "net.ports",
      "sys.terminate"
    ]
  },
  "net.ip": {
    "group": "Local network",
    "kind": "none",
    "example": "",
    "use": "Find local addresses or inspect interfaces.",
    "result": "Interface state and assigned addresses.",
    "limit": "Local namespace, not public IP.",
    "related": [
      "net.routes"
    ]
  },
  "net.routes": {
    "group": "Local network",
    "kind": "none",
    "example": "",
    "use": "Check the path used to reach a network.",
    "result": "Routes, gateways and interfaces.",
    "limit": "Main routing table; not a connectivity test.",
    "related": [
      "net.ip",
      "net.tcp"
    ]
  },
  "net.dns": {
    "group": "Connectivity tests",
    "kind": "host",
    "example": "example.com",
    "use": "A database or API hostname cannot be resolved.",
    "result": "Addresses returned by the system resolver.",
    "limit": "Uses local resolver policy.",
    "related": [
      "net.tcp"
    ]
  },
  "net.tcp": {
    "group": "Connectivity tests",
    "kind": "endpoint",
    "example": "localhost:5432",
    "use": "Check whether a database accepts TCP connections.",
    "result": "Connection outcome for the tested target.",
    "limit": "Contacts target; TCP success is not application health.",
    "related": [
      "net.dns",
      "net.ports",
      "net.http"
    ]
  },
  "net.http": {
    "group": "Connectivity tests",
    "kind": "url",
    "example": "https://example.com",
    "use": "Check an HTTP endpoint status or latency.",
    "result": "HEAD status, remote IP and duration.",
    "limit": "Contacts target; no redirects or body. HEAD can differ from GET.",
    "related": [
      "net.tcp",
      "net.tls"
    ]
  },
  "net.tls": {
    "group": "Connectivity tests",
    "kind": "tls",
    "example": "example.com:443",
    "use": "Check a trusted HTTPS certificate and expiration.",
    "result": "Verified TLS connection, subject, issuer and expiry.",
    "limit": "Contacts target; invalid certificates fail verification.",
    "related": [
      "net.http",
      "net.tcp"
    ]
  },
  "sys.host": {
    "group": "Host",
    "kind": "none",
    "example": "",
    "use": "Check OS and workstation information.",
    "result": "Host properties and filesystem snapshot.",
    "limit": "Snapshot only.",
    "related": [
      "storage.usage"
    ]
  },
  "sys.processes": {
    "group": "Processes",
    "kind": "line",
    "example": "python",
    "use": "Find a running process by name or PID.",
    "result": "Up to 100 matching processes sorted by CPU.",
    "limit": "Command arguments are not collected.",
    "related": [
      "sys.terminate",
      "net.ports"
    ]
  },
  "sys.gpu": {
    "group": "GPU",
    "kind": "none",
    "example": "",
    "use": "Check VRAM, utilization and temperature.",
    "result": "GPU metrics for each NVIDIA GPU.",
    "limit": "Requires nvidia-smi; snapshot only.",
    "related": [
      "sys.gpu-processes",
      "run:gpu-watch"
    ]
  },
  "sys.gpu-processes": {
    "group": "GPU",
    "kind": "none",
    "example": "",
    "use": "Find compute processes consuming VRAM.",
    "result": "GPU compute PID, process and memory.",
    "limit": "Driver/WSL may omit information.",
    "related": [
      "sys.gpu",
      "sys.processes"
    ]
  },
  "sys.services": {
    "group": "Services",
    "kind": "none",
    "example": "",
    "use": "Check whether system services are running.",
    "result": "Loaded systemd services and states.",
    "limit": "Requires working systemd.",
    "related": [
      "health.check"
    ]
  },
  "sys.ssh-keys": {
    "group": "SSH",
    "kind": "none",
    "example": "",
    "use": "Locate public SSH keys.",
    "result": "Public key filenames only.",
    "limit": "Does not validate server access.",
    "related": [
      "sys.ssh-agent"
    ]
  },
  "sys.ssh-agent": {
    "group": "SSH",
    "kind": "none",
    "example": "",
    "use": "Check loaded SSH identities.",
    "result": "Loaded key fingerprints.",
    "limit": "Requires accessible agent.",
    "related": [
      "sys.ssh-keys"
    ]
  },
  "sys.path": {
    "group": "Host",
    "kind": "line",
    "example": "python",
    "use": "Find duplicate or shadowed executables.",
    "result": "PATH entries or matching paths.",
    "limit": "Blank shows PATH; no execution.",
    "related": [
      "env.list"
    ]
  },
  "storage.usage": {
    "group": "Overview",
    "kind": "none",
    "example": "",
    "use": "Check if system or home disk is filling up.",
    "result": "Used and total bytes per filesystem.",
    "limit": "Root and home may share a filesystem.",
    "related": [
      "storage.largest",
      "storage.cache-sizes"
    ]
  },
  "storage.largest": {
    "group": "Inspect",
    "kind": "path",
    "example": ".",
    "use": "Find directories taking disk space.",
    "result": "Top measurable subdirectories.",
    "limit": "Scoped scan; no deletion.",
    "related": [
      "storage.files",
      "storage.usage"
    ]
  },
  "storage.files": {
    "group": "Inspect",
    "kind": "path",
    "example": ".",
    "use": "Find large files in a directory.",
    "result": "Largest files by logical size.",
    "limit": "Bounded scan; inaccessible paths may be omitted.",
    "related": [
      "storage.largest"
    ]
  },
  "storage.cache-sizes": {
    "group": "Caches",
    "kind": "none",
    "example": "",
    "use": "Find large developer/model caches.",
    "result": "Measured footprints or unknown.",
    "limit": "May overlap; no deletion.",
    "related": [
      "storage.caches",
      "legacy:clean"
    ]
  },
  "storage.caches": {
    "group": "Caches",
    "kind": "none",
    "example": "",
    "use": "Locate Python, Node and AI caches.",
    "result": "Known cache paths and presence.",
    "limit": "Location hints only.",
    "related": [
      "storage.cache-sizes"
    ]
  },
  "docker.ps": {
    "group": "Inventory",
    "kind": "none",
    "example": "",
    "use": "Find containers, state and exposed ports.",
    "result": "Local containers including stopped ones.",
    "limit": "Verified local Docker endpoint only.",
    "related": [
      "docker.logs",
      "docker.start",
      "docker.stop",
      "docker.restart"
    ]
  },
  "docker.disk": {
    "group": "Storage",
    "kind": "none",
    "example": "",
    "use": "Find Docker disk consumption.",
    "result": "Usage and reclaimable estimates.",
    "limit": "Shared layers can overlap.",
    "related": [
      "legacy:clean"
    ]
  },
  "docker.logs": {
    "group": "Inspect",
    "kind": "line",
    "example": "api",
    "use": "Investigate recent container output.",
    "result": "Last 100 log lines.",
    "limit": "May contain secrets; not persisted.",
    "related": [
      "docker.ps"
    ]
  },
  "docker.compose": {
    "group": "Inventory",
    "kind": "none",
    "example": "",
    "use": "Check services in the current Compose project.",
    "result": "Compose service/container status.",
    "limit": "Uses current directory and local endpoint.",
    "related": [
      "docker.ps",
      "docker.logs"
    ]
  },
  "agent.list": {
    "group": "Inventory",
    "kind": "none",
    "example": "",
    "use": "Discover coding agent executables.",
    "result": "Agent names and paths.",
    "limit": "PATH detection is not runtime health.",
    "related": [
      "agent.integrations",
      "agent.version"
    ]
  },
  "agent.integrations": {
    "group": "Inventory",
    "kind": "none",
    "example": "",
    "use": "Find missing RTK or Ponytail registrations.",
    "result": "Per-agent registration evidence.",
    "limit": "Not proof of runtime hook trust.",
    "related": [
      "legacy:rtk-install",
      "legacy:ponytail-install"
    ]
  },
  "agent.version": {
    "group": "Inspect",
    "kind": "agent",
    "example": "codex",
    "use": "Check active coding agent version.",
    "result": "Version reported by selected CLI.",
    "limit": "Requires agent executable.",
    "related": [
      "agent.list"
    ]
  },
  "agent.skill-updates": {
    "group": "Skills",
    "kind": "none",
    "example": "",
    "use": "Check installed skill updates.",
    "result": "Skills CLI update report.",
    "limit": "Network check; no updates applied.",
    "related": [
      "agent.skills"
    ]
  },
  "agent.skills": {
    "group": "Skills",
    "kind": "scope",
    "example": "global",
    "use": "Inspect globally or locally installed skills.",
    "result": "Skills CLI inventory.",
    "limit": "Requires Skills CLI; project scope uses cwd.",
    "related": [
      "agent.skill-updates"
    ]
  },
  "project.detect": {
    "group": "Workspace",
    "kind": "none",
    "example": "",
    "use": "Find project configuration files.",
    "result": "Directory and detected markers.",
    "limit": "No project scripts executed.",
    "related": [
      "project.git",
      "docker.compose"
    ]
  },
  "project.git": {
    "group": "Workspace",
    "kind": "none",
    "example": "",
    "use": "Check branch and tracked changes.",
    "result": "Branch and tracked working-tree status.",
    "limit": "Untracked files excluded.",
    "related": [
      "project.detect"
    ]
  },
  "util.json-format": {
    "group": "JSON",
    "kind": "editor",
    "example": "{\"name\":\"devbox\",\"ready\":true}",
    "use": "Read compact API responses or config.",
    "result": "Indented JSON or validation error.",
    "limit": "Local only; content not saved.",
    "related": [
      "util.json-minify"
    ]
  },
  "util.json-minify": {
    "group": "JSON",
    "kind": "editor",
    "example": "{\"name\":\"devbox\"}",
    "use": "Compact JSON for transport.",
    "result": "Compact JSON or error.",
    "limit": "Local only; content not saved.",
    "related": [
      "util.json-format"
    ]
  },
  "util.base64-encode": {
    "group": "Encoding",
    "kind": "editor",
    "example": "hello",
    "use": "Encode UTF-8 text for transport.",
    "result": "Base64 text.",
    "limit": "Encoding is not encryption.",
    "related": [
      "util.base64-decode"
    ]
  },
  "util.base64-decode": {
    "group": "Encoding",
    "kind": "editor",
    "example": "aGVsbG8=",
    "use": "Inspect Base64-encoded text.",
    "result": "Decoded UTF-8 text or error.",
    "limit": "Binary may not decode as UTF-8.",
    "related": [
      "util.base64-encode"
    ]
  },
  "util.url-encode": {
    "group": "Encoding",
    "kind": "editor",
    "example": "hello world",
    "use": "Escape a URL component.",
    "result": "Percent-encoded text.",
    "limit": "Not full URL validation.",
    "related": [
      "util.url-decode"
    ]
  },
  "util.url-decode": {
    "group": "Encoding",
    "kind": "editor",
    "example": "hello%20world",
    "use": "Read percent-encoded text.",
    "result": "Decoded text.",
    "limit": "Not full URL validation.",
    "related": [
      "util.url-encode"
    ]
  },
  "util.uuid": {
    "group": "Generators",
    "kind": "none",
    "example": "",
    "use": "Generate a test identifier.",
    "result": "Random UUID v4.",
    "limit": "Local random generation.",
    "related": [
      "util.uuid7"
    ]
  },
  "util.uuid7": {
    "group": "Generators",
    "kind": "none",
    "example": "",
    "use": "Generate a time-ordered identifier.",
    "result": "UUID v7.",
    "limit": "Not guaranteed monotonic within one millisecond.",
    "related": [
      "util.uuid"
    ]
  },
  "util.token": {
    "group": "Generators",
    "kind": "none",
    "example": "",
    "use": "Generate a local random secret.",
    "result": "URL-safe random token.",
    "limit": "Sensitive output; never persisted.",
    "related": []
  },
  "util.jwt": {
    "group": "Inspect",
    "kind": "editor",
    "example": "",
    "use": "Inspect compact JWT claims.",
    "result": "Decoded header and payload.",
    "limit": "Does NOT verify signature, issuer or claims.",
    "related": []
  },
  "util.timestamp": {
    "group": "Inspect",
    "kind": "line",
    "example": "1700000000",
    "use": "Convert Unix seconds to UTC.",
    "result": "UTC datetime or current Unix seconds.",
    "limit": "Seconds, not milliseconds; blank shows now.",
    "related": []
  },
  "util.sha256": {
    "group": "Inspect",
    "kind": "path",
    "example": "./model.gguf",
    "use": "Verify a downloaded file checksum.",
    "result": "Hexadecimal SHA-256 digest.",
    "limit": "Reads entire file; no modification.",
    "related": []
  }
}
GUIDES = {key: Guide(row["group"], row["kind"], row["example"], row["use"],
                     row["result"], row["limit"], tuple(row["related"]))
          for key, row in _DATA.items()}
GUIDES.update({
    "sys.terminate": Guide("Processes", "pid", "18421", "Stop a user-owned process blocking development.", "Verified SIGTERM plan and outcome.", "Changes system state; exact identity and consent required.", ("sys.processes",)),
    **{"docker." + verb: Guide("Operations", "line", "api", verb.title() + " a selected container.", "Verified local operation plan and result.", "Changes container state; exact ID, endpoint and consent required.", ("docker.ps",))
       for verb in ("start", "stop", "restart")},
})
GUIDES.update({
    "legacy:ai-setup": Guide("Setup", "none", "", "Install the Codex-first AI toolkit and selected Coding Kit skills.", "A preview of exact selected tools and skills.", "A selects Codex only plus tools and skills; other CLIs are optional. Requires confirmation.", ()),
    "legacy:install": Guide("Manage", "none", "", "Install or configure development tools.", "A component plan with dependencies and consent.", "May install packages or change configuration; review before applying.", ()),
    "legacy:upgrade": Guide("Manage", "none", "", "Update detected development tools.", "A manager-specific upgrade plan.", "External or unsupported tools may be skipped.", ()),
    "legacy:agent-install": Guide("Manage", "none", "", "Install agent extensions.", "A plan with explicit agent targets.", "Review integration targets and consent.", ()),
    "legacy:rtk-install": Guide("Manage", "none", "", "Configure RTK for selected agent CLIs.", "An explicit target plan.", "Registration does not verify hook trust.", ()),
    "legacy:ponytail-install": Guide("Manage", "none", "", "Configure Ponytail for selected agent CLIs.", "An explicit target plan.", "Registration does not verify runtime loading.", ()),
    "legacy:clean": Guide("Maintenance", "none", "", "Reclaim eligible developer cache space.", "A scoped cleanup plan.", "Manual resources require exact selection; cleanup may be irreversible.", ()),
    "legacy:doctor": Guide("Diagnostics", "none", "", "Inspect detailed host prerequisites.", "Native diagnostic report.", "Read-only; no automatic repair.", ()),
    "legacy:preflight": Guide("Diagnostics", "none", "", "Inspect host setup and compatibility.", "Host prerequisite report.", "Read-only snapshot.", ()),
    "legacy:update": Guide("Updates", "none", "", "Update Devbox itself.", "Verified source update plan.", "Exits on successful update; does not overwrite local changes.", ()),
    "legacy:theme": Guide("Preferences", "none", "", "Switch color or monochrome theme.", "Updated UI theme.", "No system changes.", ()),
    "legacy:logs": Guide("Activity", "none", "", "Review saved managed-operation logs.", "Run report and native log.", "Query inputs and outputs are not stored.", ()),
})
MODULES = {
    "Networking": ("Inspect and troubleshoot network connections.", (
        ("Server cannot start", "net.ports"), ("Database unreachable", "net.dns"),
        ("API not responding", "net.http"), ("HTTPS fails", "net.tls"))),
    "System": ("Inspect workstation, processes, GPU and SSH.", (("Find a process", "sys.processes"), ("GPU memory full", "sys.gpu-processes"), ("PATH conflicts", "sys.path"))),
    "Containers": ("Inspect local Docker and operate exact targets.", (("Find containers", "docker.ps"), ("Debug a service", "docker.logs"), ("Compose project", "docker.compose"))),
    "Storage": ("Inspect disk usage before safe cleanup.", (("Disk filling up", "storage.usage"), ("Large caches", "storage.cache-sizes"), ("Clean safely", "legacy:clean"))),
    "Environment": ("Inspect and manage development tools.", (("Tool inventory", "env.list"), ("Install tools", "legacy:install"), ("Update tools", "legacy:upgrade"))),
    "Coding Agents": ("Install agent CLIs, integrations and skills. A selects the Codex preset on the setup screen.", (("Setup AI agents", "legacy:ai-setup"), ("Check integrations", "agent.integrations"), ("Agent version", "agent.version"), ("Inspect skills", "agent.skills"))),
    "Utilities": ("Transform text and generate values locally.", (("Inspect JSON", "util.json-format"), ("Decode text", "util.base64-decode"), ("Generate ID", "util.uuid7"))),
    "Project": ("Inspect workspace or launch approved workflows.", (("Detect configuration", "project.detect"), ("Tracked changes", "project.git"))),
    "Health": ("Inspect prerequisites and diagnostic evidence.", (("Check readiness", "health.check"), ("Full Doctor", "legacy:doctor"))),
    "Settings": ("Manage preferences and source updates.", (("Update source", "legacy:update"), ("Change theme", "legacy:theme"))),
    "Favorites": ("Open saved actions. Press f to add or remove a favorite.", ()),
    "Workflows": ("Review and explicitly launch registered commands.", ()),
}
def guide_for(key):
    return GUIDES.get(key)

def command_example(key, guide):
    command = "devbox " + key.replace(".", " ", 1)
    return command + (" " + shlex.quote(guide.example) if guide.example else "")
