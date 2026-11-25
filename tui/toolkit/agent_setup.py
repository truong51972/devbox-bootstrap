"""Codex-first, explicitly confirmed AI setup catalog shared by CLI and TUI."""
from dataclasses import dataclass
from pathlib import Path
import shutil

from .workflows import Workflow

ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS = frozenset(("rtk", "ponytail", "skills-cli"))
SKILLS = (
    ("context-management", "Repository context, reflection and knowledge capture."),
    ("celery-worker", "Celery worker and task boundaries."),
    ("dependency-injection", "Python dependency injection and lifecycle."),
    ("drf-api-architecture", "Django REST Framework architecture."),
    ("python-monorepo-architecture", "Python monorepo and deployment structure."),
    ("system-prompt-builder", "Production LLM system prompts."),
)
@dataclass(frozen=True)
class SetupItem:
    key: str
    title: str
    group: str
    description: str
    default: bool = False
    executable: str = ""

ITEMS = (
    SetupItem("codex", "Codex", "AGENT CLIS", "Official Codex CLI; user-local npm install.", True, "codex"),
    SetupItem("claude", "Claude Code", "AGENT CLIS", "Optional Claude Code CLI.", False, "claude"),
    SetupItem("copilot", "GitHub Copilot CLI", "AGENT CLIS", "Optional GitHub Copilot CLI.", False, "copilot"),
    SetupItem("opencode", "OpenCode", "AGENT CLIS", "Optional OpenCode CLI (stable opencode-ai package).", False, "opencode"),
    SetupItem("gemini", "Gemini CLI", "AGENT CLIS", "Optional Gemini CLI.", False, "gemini"),
    SetupItem("rtk", "RTK", "AGENT TOOLS", "Configure token optimization for Codex only.", True, "rtk"),
    SetupItem("skills-cli", "Skills CLI", "AGENT TOOLS", "User-local Vercel Skills CLI.", True, "skills"),
    SetupItem("ponytail", "Ponytail", "AGENT TOOLS", "Install Codex plugin with lifecycle hooks.", True),
    *(SetupItem("skill:" + key, key, "CODING KIT SKILLS", desc + " Global Codex scope.", True) for key, desc in SKILLS),
)
BY_KEY = {item.key: item for item in ITEMS}
DEFAULT = tuple(item.key for item in ITEMS if item.default)


def selection(keys):
    if not keys or len(set(keys)) != len(keys) or set(keys) - set(BY_KEY):
        raise ValueError("Choose valid, unique AI setup items.")
    selected = set(keys)
    if selected & {"rtk", "ponytail"} or any(k.startswith("skill:") for k in selected):
        selected.add("codex")
    if any(k.startswith("skill:") for k in selected):
        selected.add("skills-cli")
    return tuple(item.key for item in ITEMS if item.key in selected)


def plan(keys):
    chosen = selection(keys)
    labels = ", ".join(BY_KEY[key].title for key in chosen)
    return Workflow("ai-setup", ("bash", str(ROOT / "utils/ai-setup.sh"), "--yes", *chosen),
                    "Install/verify: " + labels +
                    ". Integrations and skills target Codex, global scope. Existing CLIs are preserved. "
                    "Upstream plugins may install executable hooks; review before enabling.")


def state(item):
    if not item.executable:
        return "Not checked"
    return "Installed" if shutil.which(item.executable) else "Missing"
