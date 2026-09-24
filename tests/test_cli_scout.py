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
    assert "factory plan" in out.output
