"""Analytics schema (blueprint V5/§17): user telemetry -> next iteration.

After a product goes LIVE the factory keeps observing:

    traffic, signup, activation, retention, errors, reviews,
    support tickets, feature requests, revenue, infrastructure cost

The Analytics Agent turns raw samples into Signals / Issues / Recommendations
(Bug / Feature / Experiment / Optimization) that re-enter
Planner -> Coding Agents (blueprint §17).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    """One telemetry sample. delta_pct is change vs previous period."""

    metric: Literal[
        "traffic",
        "signup",
        "activation",
        "retention",
        "errors",
        "reviews",
        "support_tickets",
        "feature_requests",
        "revenue",
        "infrastructure_cost",
    ]
    value: float
    delta_pct: float = Field(default=0.0, description="change vs previous period, %")


class AnalyticsIssue(BaseModel):
    severity: Literal["critical", "warning", "info"]
    metric: str
    description: str


class Recommendation(BaseModel):
    kind: Literal["Bug", "Feature", "Experiment", "Optimization", "Scale", "Kill"]
    description: str
    priority: int = Field(default=0, ge=0, le=10)


class AnalyticsReport(BaseModel):
    project_id: str
    health: Literal["good", "degraded", "critical"]
    summary: str
    signals: list[str] = []
    issues: list[AnalyticsIssue] = []
    recommendations: list[Recommendation] = []

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json")
