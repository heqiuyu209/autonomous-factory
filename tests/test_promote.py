"""Milestone promotion: REVIEW -> TESTING -> ... -> PRODUCTION.

The pipeline builds through REVIEWING; `promote` is the durable, audited
walk to PRODUCTION. Eligibility is proven from the DB - every task DONE,
every review APPROVE - and an ineligible project is left untouched.
"""
from __future__ import annotations

import pytest

from factory.db import session_scope
from factory.models import Project, RunRecord
from factory.schemas.task_graph import TaskGraph
from factory.state_machine import StateMachineError
from factory.workflows import DevelopmentWorkflow


def test_promote_walks_to_production(sample_graph_path, workspace):
    wf = DevelopmentWorkflow(workspace_root=workspace)
    report = wf.build("p_demo_calc", TaskGraph.load(sample_graph_path))
    assert report["summary"]["state"] == "DONE"

    res = wf.promote("p_demo_calc")
    assert res["state"] == "PRODUCTION"
    assert res["advanced"] == [
        "TESTING",
        "SECURITY_REVIEW",
        "PERF_TEST",
        "STAGING",
        "CANARY",
        "PRODUCTION",
    ]

    with session_scope() as session:
        promo = (
            session.query(RunRecord)
            .filter_by(project_id="p_demo_calc", kind="PROMOTE")
            .all()
        )
        assert len(promo) == 6
        proj = session.get(Project, "p_demo_calc")
        assert proj.state == "PRODUCTION"

    # idempotent: already at PRODUCTION
    again = wf.promote("p_demo_calc")
    assert again["already_production"] is True
    assert again["state"] == "PRODUCTION"


def test_promote_refused_when_task_blocked(tmp_path, monkeypatch):
    """A BLOCKED (not DONE) task must refuse promotion with no mutation."""
    import time as _time

    from factory.agents import AgentInput, AgentRegistry, CoderAgent, ReviewerAgent
    from factory.orchestrator import FactoryOrchestrator
    from factory.schemas.task_graph import TaskDef, TaskGraph

    class HangingBackend:
        name = "hang"

        def run(self, task: AgentInput) -> None:  # pragma: no cover
            _time.sleep(60)
            raise AssertionError("unreachable")

    class HangingCoder(CoderAgent):
        def __init__(self):
            super().__init__(backend=HangingBackend())

    class _FakeSettings:
        verify_gates = ("syntax",)
        attempt_timeout_s = 0.3
        max_coder_retries = 1
        default_token_budget = 10000
        default_runtime_budget_s = 5
        workspace_root = tmp_path

    monkeypatch.setattr("factory.orchestrator.settings", _FakeSettings)

    reg = AgentRegistry()
    reg.register("coder", HangingCoder())
    reg.register("reviewer", ReviewerAgent())
    orch = FactoryOrchestrator(registry=reg, workspace_root=tmp_path / "ws")
    g = TaskGraph(
        project_id="p_blocked",
        name="blocked",
        tasks=[
            TaskDef(
                id="T001",
                title="never returns",
                dependencies=[],
                meta={"target": "all"},
            )
        ],
    )
    orch.run_graph("p_blocked", "blocked", graph=g, seed_bug=False)

    wf = DevelopmentWorkflow(orch, workspace_root=tmp_path / "ws")
    with pytest.raises(StateMachineError, match="not DONE"):
        wf.promote("p_blocked")
    # state left untouched: the BLOCKED task means the build never finished,
    # so the project stays at BUILDING - promote must not mutate it.
    assert DevelopmentWorkflow.status("p_blocked")["state"] == "BUILDING"


def test_promote_refused_when_review_rejected(sample_graph_path, workspace):
    """A non-APPROVE review must refuse promotion."""
    wf = DevelopmentWorkflow(workspace_root=workspace)
    wf.build("p_demo_calc", TaskGraph.load(sample_graph_path))

    with session_scope() as session:
        proj = session.get(Project, "p_demo_calc")
        review = proj.reviews[0]
        review.verdict = "REJECT"

    with pytest.raises(StateMachineError, match="reviews not APPROVE"):
        wf.promote("p_demo_calc")
    # no mutation on refusal
    assert DevelopmentWorkflow.status("p_demo_calc")["state"] == "REVIEWING"


def test_promote_missing_project(workspace):
    wf = DevelopmentWorkflow(workspace_root=workspace)
    assert wf.promote("p_nope") == {"exists": False}


def test_promote_resumes_mid_chain(sample_graph_path, workspace):
    """A crash mid-promotion must resume from the next hop, not re-apply."""
    wf = DevelopmentWorkflow(workspace_root=workspace)
    report = wf.build("p_demo_calc", TaskGraph.load(sample_graph_path))
    assert report["summary"]["state"] == "DONE"

    with session_scope() as session:
        proj = session.get(Project, "p_demo_calc")
        proj.state = "TESTING"  # simulate a crash after the first hop

    res = wf.promote("p_demo_calc")
    assert res["state"] == "PRODUCTION"
    assert res["advanced"] == [
        "SECURITY_REVIEW",
        "PERF_TEST",
        "STAGING",
        "CANARY",
        "PRODUCTION",
    ]
