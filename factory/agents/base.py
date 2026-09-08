"""Agent base contract (blueprint §24)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..policy import PolicyEngine


class AgentInput(BaseModel):
    """Universal agent input envelope."""

    agent: str  # e.g. "backend-engineer"
    project_id: str
    task_id: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(
        default_factory=lambda: {"tokens": 120000, "runtime": 1800}
    )
    workdir: str = ""  # isolated worktree path
    context: dict[str, Any] = Field(default_factory=dict)

    def policy_check(self, engine: PolicyEngine, *, internet: str = "", path: str = "") -> None:
        """Validate this run against the agent's capability policy."""
        if internet:
            engine.check_internet(self.agent, internet)
        if path:
            root = self.workdir or "."
            engine.check_filesystem(self.agent, path, root)
