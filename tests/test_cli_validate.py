"""CLI validate command tests: V4 Validation Engine driven from the CLI."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli import app
from factory.schemas.opportunity import Opportunity, OpportunityScore, PainPoint

runner = CliRunner()


def _write_opps(tmp_path: Path, evidence_count: int = 5) -> Path:
    opps = [
        Opportunity(
            opportunity_id="opp_v4",
            hypothesis="validate me",
            pains=[
                PainPoint(
                    pain_id="pain_1",
                    persona="user",
                    problem="problem",
                    evidence_count=evidence_count,
                    sources=["https://example.com/signal"],
                )
            ],
            score=OpportunityScore(
                pain_severity=0.6,
                frequency=0.6,
                willingness_to_pay=0.6,
                market_size=0.6,
                search_demand=0.6,
                competitor_weakness=0.6,
                ai_advantage=0.6,
                distribution_advantage=0.5,
                build_cost=0.05,
                acquisition_difficulty=0.1,
                regulatory_risk=0.05,
                competition_risk=0.2,
            ),
            decision="PENDING",
        )
    ]
    p = tmp_path / "opportunities.json"
    p.write_text(
        json.dumps([o.model_dump(mode="json") for o in opps], ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def test_validate_command_writes_decisions(tmp_path: Path):
    opps = _write_opps(tmp_path)
    out = runner.invoke(app, ["validate", str(opps), "--out-dir", str(tmp_path / "out")])
    assert out.exit_code == 0, out.output
    decisions = json.loads((tmp_path / "out" / "validations.json").read_text(encoding="utf-8"))
    assert decisions[0]["opportunity_id"] == "opp_v4"
    assert decisions[0]["decision"] == "TEST"


def test_validate_with_conversion_builds(tmp_path: Path):
    opps = _write_opps(tmp_path)
    out = runner.invoke(
        app,
        [
            "validate",
            str(opps),
            "--out-dir",
            str(tmp_path / "out"),
            "--conversion",
            "opp_v4=0.083",
        ],
    )
    assert out.exit_code == 0, out.output
    decisions = json.loads((tmp_path / "out" / "validations.json").read_text(encoding="utf-8"))
    assert decisions[0]["decision"] == "BUILD"


def test_validate_kills_low_evidence(tmp_path: Path):
    opps = _write_opps(tmp_path, evidence_count=0)
    out = runner.invoke(
        app,
        [
            "validate",
            str(opps),
            "--out-dir",
            str(tmp_path / "out"),
            "--conversion",
            "opp_v4=0.083",
        ],
    )
    assert out.exit_code == 0, out.output
    decisions = json.loads((tmp_path / "out" / "validations.json").read_text(encoding="utf-8"))
    assert decisions[0]["decision"] == "KILL"


def test_validate_unknown_opp_fails(tmp_path: Path):
    opps = _write_opps(tmp_path)
    out = runner.invoke(app, ["validate", str(opps), "--opp", "opp_missing", "--out-dir", str(tmp_path / "out")])
    assert out.exit_code == 1
    assert "not found" in out.output


def test_validate_bad_conversion_syntax_fails(tmp_path: Path):
    opps = _write_opps(tmp_path)
    out = runner.invoke(app, ["validate", str(opps), "--conversion", "no-equals-sign"])
    assert out.exit_code == 1
    assert "invalid --conversion" in out.output
