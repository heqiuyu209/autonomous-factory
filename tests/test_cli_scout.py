"""CLI scout command tests: Market Scout pipeline driven from the CLI."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli import app
from factory.schemas.opportunity import Opportunity

runner = CliRunner()


def test_scout_command_writes_candidates(tmp_path: Path):
    out = runner.invoke(
        app,
        [
            "scout",
            "ai meeting notes",
            "--out-dir",
            str(tmp_path),
            "--project-id",
            "p_scout_test",
            "--source",
            "github",
        ],
    )
    assert out.exit_code == 0, out.output
    json_file = tmp_path / "p_scout_test" / "opportunities.json"
    md_file = tmp_path / "p_scout_test" / "opportunities.md"
    assert json_file.exists(), out.output
    assert md_file.exists(), out.output
    data = json.loads(json_file.read_text(encoding="utf-8"))
    opp = Opportunity.model_validate(data[0])
    assert opp.opportunity_id.startswith("opp_")
    assert "Candidates" in out.output


def test_scout_plan_builds_factory_plan(tmp_path: Path):
    """V3->V2 bridge: scout --plan must auto-build PRD + task graph for the top candidate."""
    out = runner.invoke(
        app,
        [
            "scout",
            "ai meeting notes",
            "--out-dir",
            str(tmp_path),
            "--project-id",
            "p_scout_plan_test",
            "--plan",
        ],
    )
    assert out.exit_code == 0, out.output
    plan_dir = tmp_path / "plans" / "p_scout_plan_test"
    prd = plan_dir / "prd.md"
    graph = plan_dir / "task_graph.json"
    assert prd.exists(), out.output
    assert graph.exists(), out.output
    data = json.loads(graph.read_text(encoding="utf-8"))
    assert data["project_id"] == "p_scout_plan_test"
    assert "Planning top candidate" in out.output


def test_scout_plan_named_opportunity(tmp_path: Path):
    """--plan-opp must select the named candidate for planning."""
    out = runner.invoke(
        app,
        [
            "scout",
            "ai meeting notes",
            "--out-dir",
            str(tmp_path),
            "--project-id",
            "p_scout_named_test",
            "--plan",
            "--plan-opp",
            "opp_p_ai_meeting_notes",
        ],
    )
    assert out.exit_code == 0, out.output
    plan_dir = tmp_path / "plans" / "p_scout_named_test"
    assert (plan_dir / "prd.md").exists(), out.output
    assert (plan_dir / "task_graph.json").exists(), out.output
    assert "Planning top candidate: opp_p_ai_meeting_notes" in out.output


def test_scout_plan_missing_opportunity(tmp_path: Path):
    """Unknown --plan-opp must fail loudly."""
    out = runner.invoke(
        app,
        [
            "scout",
            "ai meeting notes",
            "--out-dir",
            str(tmp_path),
            "--project-id",
            "p_scout_missing_test",
            "--plan",
            "--plan-opp",
            "opp_does_not_exist",
        ],
    )
    assert out.exit_code == 1, out.output
    assert "not found" in out.output
