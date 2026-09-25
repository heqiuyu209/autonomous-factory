"""Attempt-timeout guardrail tests.

A real LLM backend can hang on a dead socket or a slow upstream for
minutes. The factory must reclaim a hung attempt as a *budget* event
(charge it, record it in the ledger) and either retry under a fresh
allowance or BLOCK the task - never stall the whole build, never leave a
daemon that blocks process exit.
"""
from __future__ import annotations

import time
from functools import partial

import pytest

from factory.agents import AgentInput, CoderAgent
from factory.execution import CoderTimeout, run_with_timeout, run_with_timeout_isolated


def test_run_with_timeout_returns_value():
    assert run_with_timeout(lambda: 42, 5.0) == 42


def test_run_with_timeout_reraises_worker_exception():
    def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_with_timeout(boom, 5.0)


def test_run_with_timeout_hits_ceiling():
    t0 = time.monotonic()
    with pytest.raises(CoderTimeout):
        run_with_timeout(lambda: time.sleep(10), 0.2)
    assert time.monotonic() - t0 < 3  # reclaimed, not waited out


def test_run_with_timeout_zero_is_immediate():
    with pytest.raises(CoderTimeout):
        run_with_timeout(lambda: 1, 0)


# --- process-isolated guard (hard kill) -------------------------------


def _iso_add(a: int, b: int) -> int:
    return a + b


def _iso_boom() -> int:
    raise ValueError("boom-iso")


def _iso_slow() -> str:
    time.sleep(60)
    return "late"


def test_isolated_returns_value():
    assert run_with_timeout_isolated(partial(_iso_add, 40, 2), 5.0) == 42


def test_isolated_reraises_worker_exception():
    with pytest.raises(ValueError, match="boom-iso"):
        run_with_timeout_isolated(_iso_boom, 5.0)


def test_isolated_hits_ceiling_and_kills():
    t0 = time.monotonic()
    with pytest.raises(CoderTimeout):
        run_with_timeout_isolated(_iso_slow, 0.5)
    assert time.monotonic() - t0 < 3  # reclaimed fast: the worker is killed
    # the worker must be gone, not lurking: a second call still works
    assert run_with_timeout_isolated(partial(_iso_add, 1, 2), 5.0) == 3


def test_isolated_zero_is_immediate():
    with pytest.raises(CoderTimeout):
        run_with_timeout_isolated(partial(_iso_add, 1, 2), 0)


class HangingBackend:
    name = "hang"

    def run(self, task: "AgentInput") -> None:  # pragma: no cover
        time.sleep(60)
        raise AssertionError("unreachable")


class HangingCoder(CoderAgent):
    def __init__(self):
        super().__init__(backend=HangingBackend())


def test_hung_coder_blocks_task(tmp_path, monkeypatch):
    """Integration: a coder that hangs past its attempt ceiling must BLOCK
    the task (not hang the build) and leave an auditable timeout in DB."""
    from factory.agents import AgentRegistry, ReviewerAgent
    from factory.orchestrator import FactoryOrchestrator
    from factory.schemas.task_graph import TaskDef, TaskGraph

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
        project_id="p_hang",
        name="hang",
        tasks=[
            TaskDef(
                id="T001",
                title="a task that never returns",
                dependencies=[],
                meta={"target": "all"},
            )
        ],
    )
    report = orch.run_graph("p_hang", "hang", graph=g, seed_bug=False)
    assert report["summary"]["state"] == "BLOCKED"
    task = report["tasks"]["T001"]
    assert task["verdict"] == "BLOCKED"
    assert "timed out" in task["reason"]

    # the burned runtime must be in the ledger for audit
    from factory.db import session_scope
    from factory.models import BudgetLedger

    with session_scope() as session:
        notes = [r.note for r in session.query(BudgetLedger).all()]
    assert any("TIMEOUT" in n or "timed out" in n for n in notes)
