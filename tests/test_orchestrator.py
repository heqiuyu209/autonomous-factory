"""End-to-end orchestrator test.

Runs the full SOFTWARE FACTORY pipeline on the bundled sample graph:
coder -> machine verifier -> reviewer -> (seeded defect triggers repair)
-> merge to main. Asserts durability, isolation and real verification.
"""
from __future__ import annotations

import pytest

from factory.agents.base import AgentInput
from factory.agents.coder import OpenAIBackend
from factory.orchestrator import FactoryOrchestrator
from factory.schemas.base import AgentOutput
from factory.schemas.task_graph import TaskDef, TaskGraph
from factory.state_machine import StateMachineError


class _DocsBackend:
    """A coder that only writes a README - produces no python at all."""

    name = "docs"

    def run(self, task):
        from pathlib import Path

        dst = Path(task.workdir) / "README.md"
        dst.write_text("# hello from factory docs task", encoding="utf-8")
        return AgentOutput(
            status="completed",
            summary="wrote documentation",
            artifacts=["README.md"],
        )


def test_full_pipeline_done_with_repair(sample_graph_path, workspace):
    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)

    report = orch.run_graph(
        project_id=graph.project_id,
        name=graph.name,
        graph=graph,
        seed_bug=True,
    )

    assert report["summary"]["state"] == "DONE"
    t1 = report["tasks"]["T001"]
    t2 = report["tasks"]["T002"]

    # T001 was seeded with a defect, so it needed at least one repair pass.
    assert t1["retries"] >= 2, f"expected a failed attempt, got {t1}"
    assert t1["repair_count"] >= 1
    assert t1["verdict"] == "APPROVE"
    assert t2["retries"] == 1
    assert t2["verdict"] == "APPROVE"


def test_merged_main_is_verified(sample_graph_path, workspace):
    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)

    main = workspace / graph.project_id / "main"
    calc = main / "sample_app" / "calc.py"
    tests = main / "tests" / "test_calc.py"
    assert calc.exists()
    assert tests.exists()
    # the merged tree must itself pass the verifier - main is clean
    from factory.verifier import Verifier

    results = Verifier(gates=("syntax", "test")).run_all(main)
    assert Verifier(gates=("syntax", "test")).summarize(results)["passed"]


def test_pipeline_ids_durable_in_db(sample_graph_path, workspace):
    """The DB reflects the run: projects, tasks, reviews persisted."""
    from factory.db import session_scope
    from factory.models import Project, ReviewRecord, TaskRecord

    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)

    with session_scope() as s:
        proj = s.get(Project, graph.project_id)
        assert proj is not None
        tasks = s.query(TaskRecord).filter_by(project_id=proj.id).all()
        assert {t.task_id for t in tasks} == {"T001", "T002"}
        assert all(t.state == "DONE" for t in tasks)
        reviews = s.query(ReviewRecord).filter_by(project_id=proj.id).all()
        assert len(reviews) >= 2


# --------------------------------------------------------------------------
# CEO acceptance gates: security, resilience, idempotence, project lifecycle
# --------------------------------------------------------------------------
def test_unsafe_project_id_rejected(workspace):
    g = TaskGraph(project_id="p_ok", name="n", tasks=[])
    orch = FactoryOrchestrator(workspace_root=workspace)
    with pytest.raises(ValueError):
        orch.run_graph("../escape", "n", g, seed_bug=False)


def test_no_code_task_done_and_merged(workspace):
    """A docs-only task must pass (syntax skips, not fails) and land in main."""
    from factory.agents import CoderAgent, ReviewerAgent
    from factory.agents.registry import AgentRegistry

    g = TaskGraph(
        project_id="p_docs",
        name="docs-only",
        tasks=[
            TaskDef(
                id="T001",
                title="write README",
                files=["README.md"],
            )
        ],
    )
    reg = AgentRegistry()
    reg.register("coder", CoderAgent(backend=_DocsBackend()))
    reg.register("reviewer", ReviewerAgent())
    orch = FactoryOrchestrator(workspace_root=workspace, registry=reg)
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    assert report["summary"]["state"] == "DONE"
    assert report["tasks"]["T001"]["verdict"] == "APPROVE"
    main_readme = workspace / "p_docs" / "main" / "README.md"
    assert main_readme.exists()


def test_zero_budget_blocks_task(workspace):
    """A task with a zero token budget must halt (BudgetExceeded), not
    silently fall back to the default ceiling."""
    g = TaskGraph(
        project_id="p_poor",
        name="no-budget",
        tasks=[TaskDef(id="T001", title="implement calc", files=["app.py"], token_budget=0)],
    )
    orch = FactoryOrchestrator(workspace_root=workspace)
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    t1 = report["tasks"]["T001"]
    assert t1["verdict"] == "BLOCKED"
    assert "budget exceeded" in t1["reason"].lower()


def test_resume_run_is_idempotent(sample_graph_path, workspace):
    """Re-running a finished graph must not re-execute any task."""
    from factory.db import session_scope
    from factory.models import RunRecord

    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    first = orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    second = orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)

    assert first["summary"]["state"] == "DONE"
    assert second["summary"]["state"] == "DONE"
    assert second["tasks"] == {}  # nothing was re-run

    with session_scope() as s:
        runs = s.query(RunRecord).filter_by(project_id=graph.project_id).count()
        assert runs == 2  # each invocation records exactly one run
        from factory.models import TaskRecord

        tasks = s.query(TaskRecord).filter_by(project_id=graph.project_id).all()
        assert all(t.state == "DONE" for t in tasks)
        assert all(t.retries == 1 for t in tasks if t.task_id == "T002")


def test_project_state_machine_advances(sample_graph_path, workspace):
    """PLANNING -> BUILDING -> REVIEWING all through the state machine."""
    from factory.db import session_scope
    from factory.models import Project

    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)

    with session_scope() as s:
        proj = s.get(Project, graph.project_id)
        assert proj.state == "REVIEWING"


def test_killed_project_refused(sample_graph_path, workspace):
    from factory.db import session_scope
    from factory.models import Project

    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)

    with session_scope() as s:
        proj = s.get(Project, graph.project_id)
        proj.state = "KILLED"

    with pytest.raises(StateMachineError):
        orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)


def test_llm_escape_payload_rejected(tmp_path):
    """LLM coder output that tries to escape the worktree must be refused
    without touching the filesystem."""
    inp = AgentInput(
        agent="coder",
        project_id="p",
        task_id="T001",
        goal="g",
        workdir=str(tmp_path / "worktree"),
    )
    (tmp_path / "worktree").mkdir()
    payload = '{"files": {"../../escape.py": "pwned"}}'
    out = OpenAIBackend._apply(inp, payload)
    assert out.status == "failed"
    assert not (tmp_path / "escape.py").exists()
    assert not (tmp_path / "worktree" / "escape.py").exists()
