"""CEO acceptance hardening round.

Covers the corners the original suite did not exercise, each mapping to a
real production risk found during the review-reject pass:

    1. review-REJECT path actually triggers a repair loop (was never hit)
    2. review-REJECT exhausted -> BLOCKED instead of infinite regression
    3. runtime budget is enforced (was silently unused before hardening)
    4. an EMPTY tests/ dir must SKIP, not fail (pytest exits 5 on it)
    5. CLI `run` exit code is the CI contract: 0 only on DONE
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from factory.agents import CoderAgent
from factory.agents.registry import AgentRegistry
from factory.budget import BudgetExceeded, BudgetTracker
from factory.schemas.base import AgentOutput
from factory.schemas.task_graph import TaskDef, TaskGraph


# --------------------------------------------------------------------------
# Deterministic backends that let us hit the REJECT branch for real
# --------------------------------------------------------------------------
class _DocsBackend:
    """Coder that emits a README only: passes verifier (both gates skip)."""

    name = "docs"

    def run(self, task):
        from pathlib import Path

        (Path(task.workdir) / "README.md").write_text("# docs", encoding="utf-8")
        return AgentOutput(status="completed", summary="docs", artifacts=["README.md"])


class _RejectThenAcceptReviewer:
    """Why substitute a real reviewer? The rule reviewer only ever REJECTs
    on missing declared files - the repair-loop branch under test was
    unreachable in the original suite. This stub flips REJECT -> APPROVE."""

    def __init__(self, rejects: int = 1):
        self._rejects_left = rejects

    def run(self, task, produced):
        if self._rejects_left > 0:
            self._rejects_left -= 1
            return {
                "verdict": "REJECT",
                "issues": [{"severity": "critical", "file": "-", "reason": "stub reject"}],
                "confidence": 0.0,
            }
        return {"verdict": "APPROVE", "issues": [], "confidence": 1.0}


class _AlwaysRejectReviewer:
    def run(self, task, produced):
        return {
            "verdict": "REJECT",
            "issues": [{"severity": "critical", "file": "-", "reason": "always"}],
            "confidence": 0.0,
        }


def _docs_graph(project_id: str = "p_reviews") -> TaskGraph:
    return TaskGraph(
        project_id=project_id,
        name="review hardening",
        tasks=[TaskDef(id="T001", title="write docs", files=["README.md"])],
    )


def _registry_with(reviewer) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register("coder", CoderAgent(backend=_DocsBackend()))
    reg.register("reviewer", reviewer)
    return reg


# --------------------------------------------------------------------------
# 1-2. Review-REJECT repair loop and its termination
# --------------------------------------------------------------------------
def test_review_reject_triggers_repair_then_approves(workspace):
    from factory.orchestrator import FactoryOrchestrator

    g = _docs_graph()
    orch = FactoryOrchestrator(
        workspace_root=workspace,
        registry=_registry_with(_RejectThenAcceptReviewer(rejects=1)),
    )
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    assert report["summary"]["state"] == "DONE"
    t1 = report["tasks"]["T001"]
    assert t1["verdict"] == "APPROVE"
    assert t1["retries"] == 2  # first attempt REJECTed, second approved
    assert t1["repair_count"] == 1


def test_review_reject_exhausted_blocks(workspace):
    from factory.orchestrator import FactoryOrchestrator

    g = _docs_graph("p_never")
    orch = FactoryOrchestrator(
        workspace_root=workspace,
        registry=_registry_with(_AlwaysRejectReviewer()),
    )
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False, max_retries=2)
    t1 = report["tasks"]["T001"]
    assert t1["verdict"] == "BLOCKED"
    assert "review rejected" in t1["reason"]
    # the factory must never merge an unapproved tree into main
    assert not (workspace / "p_never" / "main" / "README.md").exists()
    assert t1["repair_count"] == 1  # one repair pass before the ceiling hit


# --------------------------------------------------------------------------
# 3. Runtime budget is a real, enforced guard (it was dead config before)
# --------------------------------------------------------------------------
def test_runtime_budget_charge_and_remaining():
    b = BudgetTracker.from_limits(tokens=1000, runtime_s=10)
    b.charge_runtime(4, agent="coder")
    assert b.spent_runtime_s == 4
    assert b.remaining_runtime_s == 6


def test_runtime_budget_exceeded_raises():
    b = BudgetTracker.from_limits(tokens=1000, runtime_s=10)
    with pytest.raises(BudgetExceeded):
        b.charge_runtime(10.1)


def test_runtime_budget_empty_orchestrator_blocks(workspace):
    """A task whose runtime ceiling is already exhausted must BLOCK, never
    start the coder."""
    from factory.orchestrator import FactoryOrchestrator

    g = TaskGraph(
        project_id="p_slow",
        name="slow",
        tasks=[TaskDef(id="T001", title="docs", files=["README.md"], runtime_budget_s=0)],
    )
    orch = FactoryOrchestrator(workspace_root=workspace)
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    t1 = report["tasks"]["T001"]
    assert t1["verdict"] == "BLOCKED"
    assert "budget exceeded" in t1["reason"].lower()


# --------------------------------------------------------------------------
# 4. Empty tests/ directory is a skip, not a failure
# --------------------------------------------------------------------------
def test_empty_tests_dir_skipped_not_failed(tmp_path):
    from factory.verifier import Verifier, _test_files

    workdir = tmp_path / "w"
    (workdir / "tests").mkdir(parents=True)
    (workdir / "app.py").write_text("X = 1\n", encoding="utf-8")
    assert _test_files(workdir) == []
    results = Verifier(gates=("syntax", "test")).run_all(workdir)
    summary = Verifier(gates=("syntax", "test")).summarize(results)
    assert summary["passed"]
    unit = next(r for r in results if r.gate == "unit-tests")
    assert unit.skipped


# --------------------------------------------------------------------------
# 5. CLI exit code is the CI contract
# --------------------------------------------------------------------------
def _minimal_graph_json(tmp_path) -> str:
    p = tmp_path / "graph.json"
    p.write_text(json.dumps({"project_id": "p_cli", "name": "cli", "tasks": []}), encoding="utf-8")
    return str(p)


def _run_cli(graph_path: str, monkeypatch, state: str):
    import factory.cli as cli_mod

    class _FakeWF:
        def plan(self, *a, **k):
            return object()

        def build(self, *a, **k):
            return {"summary": {"state": state, "reason": "x"}, "tasks": {}}

    monkeypatch.setattr(cli_mod, "DevelopmentWorkflow", _FakeWF)
    return CliRunner().invoke(cli_mod.app, ["run", graph_path])


def test_cli_exit_zero_when_done(tmp_path, monkeypatch):
    result = _run_cli(_minimal_graph_json(tmp_path), monkeypatch, "DONE")
    assert result.exit_code == 0


def test_cli_exit_one_when_blocked(tmp_path, monkeypatch):
    result = _run_cli(_minimal_graph_json(tmp_path), monkeypatch, "BLOCKED")
    assert result.exit_code == 1
    assert "ERROR: build did not complete" in result.stdout


# --------------------------------------------------------------------------
# 6. Windows-authored task graphs: a UTF-8 BOM must not break loading
# --------------------------------------------------------------------------
def test_task_graph_load_strips_utf8_bom(tmp_path):
    from factory.schemas.task_graph import TaskGraph

    p = tmp_path / "graph.json"
    body = json.dumps(
        {"project_id": "p_bom", "name": "bom", "tasks": []},
        ensure_ascii=False,
    )
    p.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))  # BOM prefix
    g = TaskGraph.load(p)
    assert g.project_id == "p_bom"
