"""Deployment schema (blueprint V5): staged release with automatic rollback.

The factory never ships Agent -> production in one hop. Instead it walks
through smoke tests, security gate, performance gate and a canary ladder
(1% -> 5% -> 25% -> 100%); any metric regression (error up / latency up /
conversion down) triggers an automatic ROLLBACK (blueprint §16).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ReleaseStage(str, Enum):
    STAGING_SMOKE = "STAGING_SMOKE"
    SECURITY_GATE = "SECURITY_GATE"
    PERF_GATE = "PERF_GATE"
    CANARY_1 = "CANARY_1"
    CANARY_5 = "CANARY_5"
    CANARY_25 = "CANARY_25"
    CANARY_100 = "CANARY_100"


RELEASE_ORDER = [
    ReleaseStage.STAGING_SMOKE,
    ReleaseStage.SECURITY_GATE,
    ReleaseStage.PERF_GATE,
    ReleaseStage.CANARY_1,
    ReleaseStage.CANARY_5,
    ReleaseStage.CANARY_25,
    ReleaseStage.CANARY_100,
]


class GateResult(BaseModel):
    """One gate along the release ladder."""

    stage: ReleaseStage
    passed: bool
    detail: str = ""


class CanaryMetrics(BaseModel):
    """User telemetry observed during a canary stage (blueprint §16)."""

    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_pct_delta: float = Field(default=0.0, description="latency change vs baseline, %")
    conversion_pct_delta: float = Field(default=0.0, description="conversion change vs baseline, %")
    error_baseline: float = Field(default=0.0, ge=0.0, le=1.0)


class DeploymentDecision(BaseModel):
    """Outcome of a release attempt (blueprint §16: DEPLOYING/LIVE/ROLLBACK)."""

    project_id: str
    status: Literal["DEPLOYING", "ROLLED_BACK", "LIVE"]
    gates: list[GateResult] = []
    canary_metrics: dict[str, CanaryMetrics] = {}
    rolled_back_at: ReleaseStage | None = None
    rollback_reason: str = ""
    evidence: list[str] = []

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json")
