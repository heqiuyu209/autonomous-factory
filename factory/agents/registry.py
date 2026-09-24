"""Agent registry - the factory's staff directory."""
from __future__ import annotations

from .architect import ArchitectAgent
from .coder import CoderAgent, RecipeBackend
from .pm import PMAgent
from .reviewer import ReviewerAgent
from .scout import MarketScoutAgent

__all__ = [
    "AgentRegistry",
    "ArchitectAgent",
    "CoderAgent",
    "ReviewerAgent",
    "RecipeBackend",
    "PMAgent",
    "MarketScoutAgent",
]


class AgentRegistry:
    """Named access to factory agents."""

    def __init__(self):
        self._agents: dict[str, object] = {}

    def register(self, name: str, agent: object) -> None:
        self._agents[name] = agent

    def get(self, name: str):
        if name not in self._agents:
            raise KeyError(f"unknown agent '{name}'")
        return self._agents[name]

    @classmethod
    def default(cls) -> "AgentRegistry":
        reg = cls()
        reg.register("architect", ArchitectAgent())
        reg.register("coder", CoderAgent())
        reg.register("pm", PMAgent())
        reg.register("reviewer", ReviewerAgent())
        reg.register("scout", MarketScoutAgent())
        return reg
