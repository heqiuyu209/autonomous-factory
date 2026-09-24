"""CLI plan command tests: PM -> Architect pipeline driven from the CLI."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli import app
from factory.schemas.task_graph import TaskGraph

runner = CliRunner()


def test_plan_command_writes_prd_and_task_graph(tmp_path: Path):
    out = runner.invoke(
        app,
        [
            "plan",
            "build a pomodoro timer cli",
            "--out-dir",
            str(tmp_path),
            "--project-id",
            "p_plan_test",
            "--constraint",
            "python 3.11",
            "--acceptance",
            "timer starts and stops",
        ],
    )
    assert out.exit_code == 0, out.output
    prd = tmp_path / "p_plan_test" / "prd.md"
    graph_file = tmp_path / "p_plan_test" / "task_graph.json"
    assert prd.exists(), out.output
    assert graph_file.exists(), out.output
    assert "build a pomodoro timer cli" in prd.read_text(encoding="utf-8")
    graph = TaskGraph.load(graph_file)
    assert graph.project_id == "p_plan_test"
    assert {t.id for t in graph.tasks} >= {"T001", "T002"}
    # CLI contract: the next-step hint is part of the output.
    assert "factory run" in out.output
