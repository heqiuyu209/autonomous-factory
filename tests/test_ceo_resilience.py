"""CEO resilience round: crash recovery & a durable audit trail.

Maps to production risks found in the V1 baseline review:

    1. a task stranded by a crash (IN_PROGRESS / WAITING_*) must resume
       on the next `factory run` - not silently become a permanent BLOCKED
    2. the seeded-defect marker must actually persist (it did not: plain
       JSON columns ignore in-place mutation, so every rerun re-injected)
    3. budget spend claimed to be "auditable" must really land in the
       BudgetLedger table together with its account
    4. the per-task worktree must be recorded on the DB row
    5. a BLOCKED task must re-queue cleanly on the next run, never crash
       the driver
"""
from __future__ import annotations

from factory.db import init_db, session_scope
from factory.models import BudgetAccount, BudgetLedger, TaskRecord
from factory.orchestrator import FactoryOrchestrator
from factory.schemas.task_graph import TaskDef, TaskGraph
from factory.state_machine import TaskState


def _strand(sample_graph_path, workspace, t001_state: str):
    """Run once to DONE, then strandon T001 into a mid-pipeline state to
    emulate a crash that happened between DB commits."""
    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    with session_scope() as s:
        t1 = (
            s.query(TaskRecord)
            .filter_by(project_id=graph.project_id, task_id="T001")
            .one()
        )
        t1.state = t001_state
        t2 = (
            s.query(TaskRecord)
            .filter_by(project_id=graph.project_id, task_id="T002")
            .one()
        )
        t2.state = TaskState.READY.value
    return orch, graph


def test_crash_while_in_progress_resumes_to_done(sample_graph_path, workspace):
    """A task that died mid-execution must re-run to DONE on the next run,
    not be stranded as BLOCKED by an illegal IN_PROGRESS->IN_PROGRESS."""
    orch, graph = _strand(sample_graph_path, workspace, TaskState.IN_PROGRESS.value)
    report = orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    assert report["summary"]["state"] == "DONE"
    assert "T001" in report["tasks"]  # actually re-executed, not skipped


def test_crash_while_waiting_verify_resumes_to_done(sample_graph_path, workspace):
    orch, graph = _strand(
        sample_graph_path, workspace, TaskState.WAITING_VERIFY.value
    )
    report = orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    assert report["summary"]["state"] == "DONE"
    assert "T001" in report["tasks"]


def test_crash_while_waiting_review_resumes_to_done(sample_graph_path, workspace):
    orch, graph = _strand(
        sample_graph_path, workspace, TaskState.WAITING_REVIEW.value
    )
    report = orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    assert report["summary"]["state"] == "DONE"
    assert "T001" in report["tasks"]


def test_blocked_task_requeued_on_rerun(workspace):
    """A task blocked by an exhausted budget must be re-queued and re-block
    deterministically on the next run - never crash the driver."""
    g = TaskGraph(
        project_id="p_req",
        name="requeue",
        tasks=[
            TaskDef(
                id="T001",
                title="calc",
                files=["app.py"],
                token_budget=0,
            )
        ],
    )
    orch = FactoryOrchestrator(workspace_root=workspace)
    r1 = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    assert r1["summary"]["state"] == "BLOCKED"
    r2 = orch.run_graph(g.project_id, g.name, g, seed_bug=False)
    assert r2["summary"]["state"] == "BLOCKED"
    assert r2["tasks"]["T001"]["verdict"] == "BLOCKED"


def test_seed_marker_and_workdir_persist(sample_graph_path, workspace):
    """detail/seed and workdir changes must survive the session commit."""
    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    with session_scope() as s:
        t1 = (
            s.query(TaskRecord)
            .filter_by(project_id=graph.project_id, task_id="T001")
            .one()
        )
        assert t1.detail.get("seeded") is True
        assert t1.workdir is not None
        assert t1.workdir.replace("\\", "/").endswith("worktrees/T001")


def test_budget_spend_is_durable_in_ledger(sample_graph_path, workspace):
    """Every charge mirrors into BudgetLedger under a project account, so
    the 'auditable spend' claim in the blueprint actually holds."""
    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    orch.run_graph(graph.project_id, graph.name, graph, seed_bug=True)
    with session_scope() as s:
        account = s.get(BudgetAccount, f"project:{graph.project_id}")
        assert account is not None
        rows = (
            s.query(BudgetLedger).filter_by(account_id=account.id).all()
        )
        # T001 token+rt rows (>=2 attempts due to seed) + T002 -> >= 4 rows
        assert len(rows) >= 4
        assert any(r.cost_tokens > 0 for r in rows)
        assert all(r.cost_usd == 0.0 for r in rows)  # recipe backend is free
        assert any(r.cost_runtime_s >= 0 for r in rows)  # wall-clock rows too


def test_ledger_write_is_idempotent(sample_graph_path, workspace):
    """Crash recovery re-runs a task from attempt 1; re-charging the same
    (account, ref) must not violate the UNIQUE constraint on the ledger."""
    init_db()
    graph = TaskGraph.load(sample_graph_path)
    orch = FactoryOrchestrator(workspace_root=workspace)
    with session_scope() as s:
        account_id = orch._ensure_budget_account(s, graph.project_id)
        orch._write_ledger(
            s, account_id, ref="T001#1", tokens=10, agent="coder", note="attempt 1"
        )
        s.flush()
        orch._write_ledger(
            s, account_id, ref="T001#1", tokens=10, agent="coder", note="attempt 1"
        )
        s.flush()  # must not raise IntegrityError
        rows = (
            s.query(BudgetLedger)
            .filter_by(account_id=account_id, ref_id="T001#1")
            .all()
        )
        assert len(rows) == 1
