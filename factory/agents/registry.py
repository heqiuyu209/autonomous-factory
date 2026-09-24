"""Agent registry - the factory's staff directory."""
from __future__ import annotations

from .coder import CoderAgent, RecipeBackend
from .pm import PMAgent
from .reviewer import ReviewerAgent

__all__ = [
    "AgentRegistry",
    "CoderAgent",
    "ReviewerAgent",
    "RecipeBackend",
    "PMAgent",
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
        reg.register("coder", CoderAgent())
        reg.register("pm", PMAgent())
        reg.register("reviewer", ReviewerAgent())
        return reg
