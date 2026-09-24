"""Market Scout Agent tests: deterministic opportunity candidate generation,
backend auto-selection, and registry wiring."""
from __future__ import annotations

import json
from pathlib import Path

from factory.agents.base import AgentInput
from factory.agents.registry import AgentRegistry
from factory.agents.scout import (
    OPPORTUNITIES_JSON,
    OPPORTUNITIES_MD,
    MarketScoutAgent,
    RecipeBackend,
)
from factory.schemas.opportunity import Opportunity


def _scout_task(tmp_path: Path, query: str = "ai meeting notes") -> AgentInput:
    return AgentInput(
        agent="scout",
        project_id="p1",
        task_id="t1",
        goal=query,
        constraints=["github", "search"],
        workdir=str(tmp_path),
    )


def test_recipe_backend_writes_json_and_md(tmp_path: Path):
    out = RecipeBackend().run(_scout_task(tmp_path))
    assert out.status == "completed"
    assert OPPORTUNITIES_JSON in out.artifacts
    assert OPPORTUNITIES_MD in out.artifacts
    data = json.loads((tmp_path / OPPORTUNITIES_JSON).read_text(encoding="utf-8"))
    opp = Opportunity.model_validate(data[0])
    assert opp.opportunity_id.startswith("opp_")
    assert opp.decision == "PENDING"
    assert opp.pains
    assert opp.score.total() >= 0
    md = (tmp_path / OPPORTUNITIES_MD).read_text(encoding="utf-8")
    assert "Market Scout" in md
    assert opp.hypothesis in md


def test_recipe_backend_is_deterministic(tmp_path: Path):
    task = _scout_task(tmp_path, query="meeting")
    RecipeBackend().run(task)
    first = (tmp_path / OPPORTUNITIES_JSON).read_text(encoding="utf-8")
    out = RecipeBackend().run(task)
    assert out.status == "completed"
    second = (tmp_path / OPPORTUNITIES_JSON).read_text(encoding="utf-8")
    assert first == second


def test_recipe_backend_embeds_query_and_sources(tmp_path: Path):
    out = RecipeBackend().run(_scout_task(tmp_path, query="meeting summarizer"))
    assert out.status == "completed"
    md = (tmp_path / OPPORTUNITIES_MD).read_text(encoding="utf-8")
    assert "meeting summarizer" in md
    assert "github" in md


def test_scout_agent_uses_recipe_backend_without_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent = MarketScoutAgent()
    assert agent.backend.name == "recipe"
    out = agent.run(_scout_task(tmp_path))
    assert out.status == "completed"
    assert (tmp_path / OPPORTUNITIES_JSON).exists()


def test_registry_exposes_scout_agent():
    reg = AgentRegistry.default()
    assert reg.get("scout") is not None
    assert isinstance(reg.get("scout"), MarketScoutAgent)
