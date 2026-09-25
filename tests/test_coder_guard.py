"""Coder failed-output guard (CEO hardening round).

A real LLM backend is fallible: upstream outages, invalid JSON, unsafe
paths. Those failures are *attempt* failures, not factory crashes. These
tests pin the orchestrator contract:

    1. a coder that always fails must block that task cleanly - the whole
       `run_graph` must NOT blow up with an unhandled exception;
    2. a transient failure must be repaired by a later healthy attempt,
       exactly like the seeded-bug / verifier repair loop.
"""
from __future__ import annotations

from types import SimpleNamespace

from factory.agents import CoderAgent
from factory.agents.registry import AgentRegistry
from factory.agents.reviewer import ReviewerAgent
from factory.orchestrator import FactoryOrchestrator
from factory.schemas.base import AgentOutput
from factory.schemas.task_graph import TaskDef, TaskGraph

_DEFAULT = dict(
    verify_gates=("syntax",),
    attempt_timeout_s=30,
    max_coder_retries=1,
    default_token_budget=10000,
    default_runtime_budget_s=60,
    workspace_root="unused",
)


def _build_orch(tmp_path, monkeypatch, backend, *, max_coder_retries: int):
    cfg = dict(_DEFAULT)
    cfg["max_coder_retries"] = max_coder_retries
    cfg["workspace_root"] = tmp_path
    monkeypatch.setattr(
        "factory.orchestrator.settings",
        SimpleNamespace(**cfg),
    )
    reg = AgentRegistry()
    reg.register("coder", CoderAgent(backend=backend))
    reg.register("reviewer", ReviewerAgent())
    return FactoryOrchestrator(registry=reg, workspace_root=tmp_path / "ws")


def _graph():
    return TaskGraph(
        project_id="p_fail",
        name="fail",
        tasks=[TaskDef(id="T001", title="gen code", files=["app.py"])],
    )


class AlwaysFailBackend:
    name = "always-fail"

    def run(self, _task):
        return AgentOutput(status="failed", summary="LLM backend error: outage")


def test_permanent_coder_failure_blocks_not_crash(tmp_path, monkeypatch):
    """Exhausted retries on a failing LLM backend must end in BLOCKED with
    a clean driver exit - never an unhandled exception out of run_graph."""
    orch = _build_orch(
        tmp_path, monkeypatch, AlwaysFailBackend(), max_coder_retries=1
    )
    g = _graph()
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    assert report["summary"]["state"] == "BLOCKED"
    t = report["tasks"]["T001"]
    assert t["verdict"] == "BLOCKED"
    # the failed-attempt reason is surfaced, not swallowed
    assert "LLM backend error" in t.get("reason", "")


class FailOnceBackend:
    """Fails the first attempt, succeeds on the second.

    Attempts run in separate spawned processes (hard-timeout isolation), so
    instance state cannot travel between attempts. The attempt counter is
    carried in a workdir marker file instead.
    """

    name = "fail-once"

    def run(self, task):
        from pathlib import Path

        # Keep the counter OUTSIDE the worktree: the orchestrator drops the
        # tree (rmtree) between failed attempts, which would erase in-tree
        # state. A sibling marker survives resets and crosses process
        # boundaries.
        marker = Path(task.workdir).parent / f".fail_once_count_{task.task_id}"
        attempt_no = int(marker.read_text(encoding="utf-8")) if marker.exists() else 0
        marker.write_text(str(attempt_no + 1), encoding="utf-8")
        if attempt_no == 0:
            return AgentOutput(status="failed", summary="LLM transient error")
        # second attempt succeeds and genuinely writes the declared file, so
        # the machine verifier + rule reviewer can both pass
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        return AgentOutput(
            status="completed", summary="wrote app.py", artifacts=["app.py"]
        )


def test_transient_coder_failure_is_repaired(tmp_path, monkeypatch):
    """A one-off LLM failure must be repaired by the next attempt, mirroring
    the seeded-bug loop, and end the task DONE."""
    orch = _build_orch(
        tmp_path, monkeypatch, FailOnceBackend(), max_coder_retries=2
    )
    g = _graph()
    report = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    assert report["summary"]["state"] == "DONE"
    t = report["tasks"]["T001"]
    assert t["verdict"] == "APPROVE"
    assert t["retries"] == 2
    assert t["repair_count"] == 1
