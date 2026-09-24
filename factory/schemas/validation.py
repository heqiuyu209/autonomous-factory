"""Validation decision schema (blueprint §6 / §26 - V4 Validation Engine).

Mirrors the Product Council flow:

    IDEA -> Evidence gate -> cheap experiment -> Conversion gate -> BUILD

KILL is always a final verdict; TEST means "evidence is sufficient, run a
cheap experiment next"; BUILD requires both gates to pass (optionally with
a measured conversion rate from a real experiment).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationDecision(BaseModel):
    opportunity_id: str
    hypothesis: str = ""

    # evidence gate
    evidence_score: float = 0.0
    evidence_threshold: float = 0.4
    evidence_gate: str = "FAIL"  # PASS | FAIL

    # cheap experiment / conversion gate
    conversion_rate: float | None = None  # measured landing/waitlist conversion
    conversion_threshold: float = 0.03
    conversion_gate: str | None = None  # PASS | FAIL | None (no experiment data)

    decision: str = "KILL"  # KILL | TEST | BUILD
    confidence: float = 0.0

    # devil's advocate objections + judge reasoning
    objections: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    def to_json_dict(self) -> dict:
        return self.model_dump()
