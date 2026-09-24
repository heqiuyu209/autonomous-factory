"""Opportunity / Pain model (blueprint §3-4, V4+).

Kept minimal in V1 - the SOFTWARE FACTORY does not hunt markets yet,
but the schema mirrors the blueprint so V4 can bolt on later.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class PainPoint(BaseModel):
    pain_id: str
    persona: str
    problem: str
    frequency: str = ""
    severity: float = 0.0
    current_solution: str = ""
    willingness_to_pay: float = 0.0
    evidence_count: int = 0
    sources: list[str] = Field(default_factory=list)


class OpportunityScore(BaseModel):
    pain_severity: float = 0.0
    frequency: float = 0.0
    willingness_to_pay: float = 0.0
    market_size: float = 0.0
    search_demand: float = 0.0
    competitor_weakness: float = 0.0
    ai_advantage: float = 0.0
    distribution_advantage: float = 0.0
    build_cost: float = 0.0
    acquisition_difficulty: float = 0.0
    regulatory_risk: float = 0.0
    competition_risk: float = 0.0

    # blueprint §4 weighting
    WEIGHTS: ClassVar[dict[str, float]] = {
        "pain_severity": 0.20,
        "frequency": 0.15,
        "willingness_to_pay": 0.15,
        "market_size": 0.15,
        "search_demand": 0.10,
        "competitor_weakness": 0.10,
        "ai_advantage": 0.10,
        "distribution_advantage": 0.05,
    }

    def total(self) -> float:
        score = 0.0
        for field_, w in self.WEIGHTS.items():
            score += getattr(self, field_) * w
        score -= self.build_cost
        score -= self.acquisition_difficulty
        score -= self.regulatory_risk
        score -= self.competition_risk
        return round(score, 2)


class Opportunity(BaseModel):
    opportunity_id: str
    hypothesis: str
    pains: list[PainPoint] = Field(default_factory=list)
    score: OpportunityScore = Field(default_factory=OpportunityScore)
    decision: str = "PENDING"  # PENDING | BUILD | TEST | KILL
