"""Orchestrator-level budget-halt + verify-exhaustion tests.

The factory's core promise is that budget/policy violations and gate
failures HALT the pipeline explicitly (BLOCKED) instead of being swallowed
or crashing the process. These integration tests prove that promise at the
orchestrator boundary:

  * a task whose coder output exceeds its token ceiling lands in a durable
    BLOCKED state with an explicit reason - never a half-verified merge,
    never an unhandled exception;
  * a permanently-failing machine verifier consumes its retries and then
    BLOCKs the task instead of merging unverified code.
"""
from __future__ import annotations

from factory.agents import AgentRegistry, CoderAgent, ReviewerAgent
from factory.orchestrator import FactoryOrchestrator
from factory.schemas.task_graph import TaskDef, TaskGraph
from factory.verifier import GateResult, Verifier


def _make_graph(project_id: str, *, token_budget: int | None = None) -> TaskGraph:
    return TaskGraph(
        project_id=project_id,
        name="halt",
        tasks=[
            TaskDef(
                id="T001",
                title="produce a module with tests",
                dependencies=[],
                files=["sample_app/calc.py", "tests/test_calc.py"],
                token_budget=token_budget,
                meta={"target": "all"},
            )
        ],
    )


def _make_orch(tmp_path):
    reg = AgentRegistry()
    reg.register("coder", CoderAgent())  # RecipeBackend: deterministic
    reg.register("reviewer", ReviewerAgent())
    return FactoryOrchestrator(registry=reg, workspace_root=tmp_path / "ws")


def test_token_budget_exhaustion_halts_task(tmp_path):
    """A coder output that exceeds the task token ceiling must BLOCK the
    task (not crash the build, not merge)."""
    orch = _make_orch(tmp_path)
    # RecipeBackend emits a ~44-char summary; a 1-token ceiling forces the
    # first charge to blow past the budget.
    g = _make_graph("p_thirsty", token_budget=1)
    report = orch.run_graph("p_thirsty", "halt", graph=g, seed_bug=False)

    assert report["summary"]["state"] == "BLOCKED"
    task = report["tasks"]["T001"]
    assert task["verdict"] == "BLOCKED"
    assert "budget exceeded" in task["reason"]


class _AlwaysFailVerifier(Verifier):
    def run_all(self, workdir):  # noqa: D102
        return [GateResult("syntax", False, "syntax blowup (forced)")]


def test_verify_always_fail_blocks_after_retries(tmp_path):
    """When the machine verifier can never pass, the orchestrator must use
    its retries, then land in a durable BLOCKED - never merge bad code."""
    reg = AgentRegistry()
    reg.register("coder", CoderAgent())
    reg.register("reviewer", ReviewerAgent())
    orch = FactoryOrchestrator(
        registry=reg, verifier=_AlwaysFailVerifier(), workspace_root=tmp_path / "ws"
    )
    g = _make_graph("p_badcode")
    report = orch.run_graph(
        "p_badcode", "halt", graph=g, seed_bug=False, max_retries=2
    )

    assert report["summary"]["state"] == "BLOCKED"
    task = report["tasks"]["T001"]
    assert task["verdict"] == "BLOCKED"
    assert task["retries"] == 2  # initial attempt + one repair attempt
    assert task["repair_count"] == 1
    assert "verification failed" in task["reason"]
