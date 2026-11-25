"""Presentation-neutral inventory records shared by CLI and TUI."""
from dataclasses import dataclass
from tui.agent_status import PluginStatus


@dataclass(frozen=True)
class ToolRow:
    key: str
    name: str
    category: str
    state: str
    path: str
    evidence: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentRow:
    key: str
    name: str
    cli: str
    path: str
    rtk: PluginStatus
    ponytail: PluginStatus


@dataclass(frozen=True)
class AgentMatrix:
    binary: PluginStatus
    agents: tuple[AgentRow, ...]
