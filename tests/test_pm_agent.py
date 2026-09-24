"""PM Agent tests: deterministic PRD generation, backend auto-selection,
and registry wiring."""
from __future__ import annotations

from pathlib import Path

from factory.agents.base import AgentInput
from factory.agents.pm import PRD_FILENAME, PMAgent, RecipeBackend
from factory.agents.registry import AgentRegistry


def _pm_task(tmp_path: Path, goal: str = "build a todo list app") -> AgentInput:
    return AgentInput(
        agent="pm",
        project_id="p1",
        task_id="t1",
        goal=goal,
        constraints=["python 3.11", "no external service"],
        acceptance_criteria=["CLI runs", "tests pass"],
        workdir=str(tmp_path),
    )


def test_recipe_backend_writes_prd_with_goal(tmp_path: Path):
    out = RecipeBackend().run(_pm_task(tmp_path))
    assert out.status == "completed"
    assert PRD_FILENAME in out.artifacts
    prd = (tmp_path / PRD_FILENAME).read_text(encoding="utf-8")
    assert "build a todo list app" in prd
    assert "## Goal" in prd
    assert "## Acceptance criteria" in prd


def test_recipe_backend_embeds_constraints_and_acceptance(tmp_path: Path):
    out = RecipeBackend().run(_pm_task(tmp_path))
    assert out.status == "completed"
    prd = (tmp_path / PRD_FILENAME).read_text(encoding="utf-8")
    assert "python 3.11" in prd
    assert "no external service" in prd
    assert "CLI runs" in prd
    assert "tests pass" in prd


def test_pm_agent_uses_recipe_backend_without_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent = PMAgent()
    assert agent.backend.name == "recipe"
    out = agent.run(_pm_task(tmp_path))
    assert out.status == "completed"
    assert (tmp_path / PRD_FILENAME).exists()


def test_registry_exposes_pm_agent():
    reg = AgentRegistry.default()
    assert reg.get("pm") is not None
    assert isinstance(reg.get("pm"), PMAgent)
