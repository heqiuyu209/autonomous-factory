"""CLI exit-code contract tests.

The CLI is the CI integration surface: a scripted `factory run` must signal
"build finished cleanly" via exit 0 and anything short of that (BLOCKED /
refused promote) via a non-zero exit. These tests pin that contract.
"""
from __future__ import annotations

from typer.testing import CliRunner

from factory.cli import app
from factory.state_machine import StateMachineError
from factory.workflows import DevelopmentWorkflow

runner = CliRunner()


def test_cli_run_done_exits_zero(sample_graph_path):
    """A fully-executed graph must exit 0 (the CI success signal)."""
    res = runner.invoke(app, ["run", str(sample_graph_path), "--no-seed-bug"])
    assert res.exit_code == 0, res.stdout
    assert "DONE" in res.stdout


def test_cli_run_blocked_exits_one(monkeypatch, sample_graph_path):
    """Anything short of DONE must exit 1 with an explicit ERROR line so a
    script can distinguish failure from success (never a silent 0)."""
    def _fake_build(self, project_id, graph, seed_bug=True):
        return {"summary": {"state": "BLOCKED", "reason": "budget exceeded"},
                "tasks": {"T001": {"verdict": "BLOCKED", "retries": 0,
                                   "repair_count": 0, "gates": []}}}

    monkeypatch.setattr(DevelopmentWorkflow, "build", _fake_build)
    res = runner.invoke(app, ["run", str(sample_graph_path)])
    assert res.exit_code == 1
    assert "ERROR" in res.stdout
    assert "BLOCKED" in res.stdout


def test_cli_promote_refused_exits_one_on_illegal_transition(monkeypatch):
    """A promote that violates the state machine must be refused loudly."""
    def _bad_promote(self, project_id):
        raise StateMachineError("illegal transition REVIEWING->PRODUCTION")

    monkeypatch.setattr(DevelopmentWorkflow, "promote", _bad_promote)
    res = runner.invoke(app, ["promote", "p_whatever"])
    assert res.exit_code == 1
    assert "promote refused" in res.stdout


def test_cli_promote_missing_project_exits_one(monkeypatch):
    """Promote on a project the factory has no record of must exit 1."""
    monkeypatch.setattr(
        DevelopmentWorkflow,
        "promote",
        lambda self, project_id: {"exists": False},
    )
    res = runner.invoke(app, ["promote", "p_ghost"])
    assert res.exit_code == 1


def test_cli_demo_missing_sample_exits_one(monkeypatch, tmp_path):
    """`factory demo` without the bundled sample must fail loudly, not hang."""
    import factory.cli as cli_mod

    missing = tmp_path / "no_such_sample"
    monkeypatch.setattr(cli_mod, "_DEMO_DIR", missing)
    res = runner.invoke(app, ["demo"])
    assert res.exit_code == 1
    assert "sample project not found" in res.stdout
