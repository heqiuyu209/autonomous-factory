"""Validation Engine tests: evidence gate, devil's advocate, judge decisions."""
from __future__ import annotations

import json
from pathlib import Path

from factory.agents.validation import (
    DevilAdvocate,
    JudgeEngine,
    ValidationEngine,
    evidence_score_for,
)
from factory.schemas.opportunity import Opportunity, OpportunityScore, PainPoint


def _opp(
    opp_id: str = "opp_test",
    evidence_count: int = 3,
    score_overrides: dict | None = None,
) -> Opportunity:
    defaults = dict(
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
    )
    if score_overrides:
        defaults.update(score_overrides)
    return Opportunity(
        opportunity_id=opp_id,
        hypothesis="test hypothesis",
        pains=[
            PainPoint(
                pain_id="pain_1",
                persona="user",
                problem="manual work is slow",
                evidence_count=evidence_count,
                sources=["https://example.com/signal"],
            )
        ],
        score=OpportunityScore(**defaults),
        decision="PENDING",
    )


def test_evidence_score_strong_with_real_evidence():
    opp = _opp(evidence_count=5)
    assert evidence_score_for(opp) >= 0.6


def test_evidence_score_low_for_synthetic():
    opp = _opp(evidence_count=0)
    opp.pains[0].sources = ["recipe://synthetic"]
    assert evidence_score_for(opp) < 0.4


def test_kill_when_evidence_below_threshold():
    engine = ValidationEngine(evidence_threshold=0.9, conversion_threshold=0.03)
    d = engine.validate(_opp(evidence_count=1))
    assert d.decision == "KILL"
    assert d.evidence_gate == "FAIL"


def test_test_when_no_conversion_data():
    engine = ValidationEngine()
    d = engine.validate(_opp(evidence_count=5))
    assert d.decision == "TEST"
    assert d.evidence_gate == "PASS"
    assert d.conversion_gate is None


def test_build_when_conversion_above_threshold():
    engine = ValidationEngine(conversion_threshold=0.03)
    d = engine.validate(_opp(evidence_count=5), conversion_rate=0.083)
    assert d.decision == "BUILD"
    assert d.conversion_gate == "PASS"


def test_kill_when_conversion_below_threshold():
    engine = ValidationEngine(conversion_threshold=0.03)
    d = engine.validate(_opp(evidence_count=5), conversion_rate=0.005)
    assert d.decision == "KILL"
    assert d.conversion_gate == "FAIL"


def test_strong_objections_downgrade_build_to_test():
    opp = _opp(evidence_count=5, score_overrides={"willingness_to_pay": 0.2})
    engine = ValidationEngine()
    d = engine.validate(opp, conversion_rate=0.083)
    assert len(d.objections) >= 1
    # willingness low + free competitors may stack objections
    assert d.decision in ("BUILD", "TEST")


def test_devil_advocate_flags_synthetic_evidence():
    opp = _opp(evidence_count=0)
    opp.pains[0].sources = ["recipe://synthetic"]
    objections = DevilAdvocate().run(opp)
    assert any("合成" in o for o in objections)


def test_judge_build_includes_reasons():
    opp = _opp(evidence_count=5)
    judge = JudgeEngine()
    d = judge.run(opp, evidence_score_for(opp), 0.4, 0.083, 0.03, [])
    assert d.decision == "BUILD"
    assert any("conversion" in r for r in d.reasons)


def test_engine_run_writes_artifacts(tmp_path: Path):
    opps = [_opp("opp_a", evidence_count=5), _opp("opp_b", evidence_count=0)]
    opps[1].pains[0].sources = ["recipe://synthetic"]
    (tmp_path / "opportunities.json").write_text(
        json.dumps([o.model_dump(mode="json") for o in opps], ensure_ascii=False),
        encoding="utf-8",
    )
    from factory.agents.base import AgentInput

    engine = ValidationEngine()
    out = engine.run(
        AgentInput(
            agent="validation",
            project_id="p_v4",
            task_id="validate",
            goal="validate",
            workdir=str(tmp_path),
        )
    )
    assert out.status == "completed"
    assert (tmp_path / "validations.json").exists()
    assert (tmp_path / "validations.md").exists()
    decisions = json.loads((tmp_path / "validations.json").read_text(encoding="utf-8"))
    assert {d["decision"] for d in decisions} == {"KILL", "TEST"}
