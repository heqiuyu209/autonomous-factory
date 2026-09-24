"""Architect Agent tests: deterministic task-graph generation from a PRD,
PM -> Architect recipe end-to-end, DAG validity, and registry wiring."""
from __future__ import annotations

from pathlib import Path

from factory.agents.architect import (
    GRAPH_FILENAME,
    ArchitectAgent,
    RecipeBackend,
)
from factory.agents.base import AgentInput
from factory.agents.pm import PMAgent
from factory.agents.registry import AgentRegistry
from factory.schemas.task_graph import TaskGraph


def _arch_task(tmp_path: Path) -> AgentInput:
    return AgentInput(
        agent="architect",
        project_id="p_arch",
        task_id="a1",
        goal="build a todo list app",
        workdir=str(tmp_path),
    )


def test_recipe_backend_writes_valid_task_graph(tmp_path: Path):
    # Architect recipe reads prd.md from the workdir; seed one first.
    (tmp_path / "prd.md").write_text(
        "# Product\n\n## Goal\nbuild a todo list app\n\n"
        "## Acceptance criteria\n- CLI runs\n- tests pass\n",
        encoding="utf-8",
    )
    out = RecipeBackend().run(_arch_task(tmp_path))
    assert out.status == "completed"
    assert GRAPH_FILENAME in out.artifacts
    graph = TaskGraph.load(tmp_path / GRAPH_FILENAME)
    assert graph.project_id == "p_arch"
    ids = [t.id for t in graph.tasks]
    assert "T001" in ids and "T002" in ids
    # DAG contract: T002 depends on T001, never the reverse.
    t2 = graph.by_id("T002")
    assert t2.dependencies == ["T001"]


def test_pm_to_architect_recipe_end_to_end(tmp_path: Path):
    pm = PMAgent()
    pm_out = pm.run(
        AgentInput(
            agent="pm",
            project_id="p_e2e",
            task_id="t1",
            goal="build a weather cli",
            workdir=str(tmp_path),
        )
    )
    assert pm_out.status == "completed"
    arch = ArchitectAgent()
    arch_out = arch.run(
        AgentInput(
            agent="architect",
            project_id="p_e2e",
            task_id="a1",
            goal="build a weather cli",
            workdir=str(tmp_path),
        )
    )
    assert arch_out.status == "completed"
    graph = TaskGraph.load(tmp_path / GRAPH_FILENAME)
    # Recipe architect should carry the PRD goal into the graph name.
    assert "weather cli" in graph.name


def test_architect_uses_recipe_backend_without_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent = ArchitectAgent()
    assert agent.backend.name == "recipe"


def test_registry_exposes_architect_agent():
    reg = AgentRegistry.default()
    assert isinstance(reg.get("architect"), ArchitectAgent)
