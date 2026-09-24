"""Analytics Agent (blueprint V5/§17): telemetry -> Bug/Feature/Experiment.

Deterministic rule engine over telemetry samples. No LLM required; it maps
the signals the blueprint tells the factory to watch (traffic, signup,
activation, retention, errors, reviews, support tickets, feature requests,
revenue, infrastructure cost) into Issues and Recommendations that re-enter
Planner -> Coding Agents.
"""
from __future__ import annotations

from ..schemas.analytics import (
    AnalyticsIssue,
    AnalyticsReport,
    MetricSample,
    Recommendation,
)

_ERROR_RATE_CRITICAL = 0.05
_ERROR_RATE_WARNING = 0.02
_GROWTH_DROP_WARNING = -15.0
_RETENTION_WARNING = 0.30


class AnalyticsEngine:
    def analyze(
        self,
        samples: list[MetricSample],
        *,
        project_id: str = "p_unknown",
        metrics_path: str = "",
    ) -> AnalyticsReport:
        by = {s.metric: s for s in samples}
        signals: list[str] = []
        issues: list[AnalyticsIssue] = []
        recs: list[Recommendation] = []

        def get(name: str) -> MetricSample | None:
            return by.get(name)

        # --- traffic / growth ---
        traffic = get("traffic")
        if traffic:
            if traffic.delta_pct >= 10:
                signals.append(f"traffic +{traffic.delta_pct:.0f}%")
                recs.append(Recommendation(kind="Scale", description="traffic growing -> scale infrastructure / capacity", priority=6))
            elif traffic.delta_pct <= _GROWTH_DROP_WARNING:
                issues.append(AnalyticsIssue(severity="warning", metric="traffic", description=f"traffic dropped {traffic.delta_pct:.0f}%"))
                recs.append(Recommendation(kind="Experiment", description="traffic drop -> run acquisition experiment", priority=7))

        # --- errors ---
        errors = get("errors")
        error_rate = errors.value if errors else 0.0
        if error_rate >= _ERROR_RATE_CRITICAL:
            issues.append(AnalyticsIssue(severity="critical", metric="errors", description=f"error rate {error_rate:.1%} >= 5%"))
            recs.append(Recommendation(kind="Bug", description=f"fix critical errors (rate {error_rate:.1%})", priority=10))
        elif error_rate >= _ERROR_RATE_WARNING:
            issues.append(AnalyticsIssue(severity="warning", metric="errors", description=f"error rate {error_rate:.1%} >= 2%"))
            recs.append(Recommendation(kind="Bug", description=f"investigate elevated error rate {error_rate:.1%}", priority=7))

        # --- activation ---
        activation = get("activation")
        if activation and activation.delta_pct < 0:
            issues.append(AnalyticsIssue(severity="warning", metric="activation", description=f"activation down {activation.delta_pct:.0f}%"))
            recs.append(Recommendation(kind="Experiment", description="activation decline -> onboarding experiment", priority=8))

        # --- retention ---
        retention = get("retention")
        if retention and retention.value < _RETENTION_WARNING:
            issues.append(AnalyticsIssue(severity="warning", metric="retention", description=f"retention {retention.value:.0%} < 30%"))
            recs.append(Recommendation(kind="Optimization", description="low retention -> engagement/retention loop", priority=8))

        # --- support tickets ---
        tickets = get("support_tickets")
        if tickets and tickets.delta_pct >= 20:
            issues.append(AnalyticsIssue(severity="warning", metric="support_tickets", description=f"support tickets +{tickets.delta_pct:.0f}%"))
            recs.append(Recommendation(kind="Bug", description="support ticket surge -> find root cause", priority=7))

        # --- feature requests ---
        fr = get("feature_requests")
        if fr and fr.delta_pct >= 15:
            signals.append(f"feature_requests +{fr.delta_pct:.0f}%")
            recs.append(Recommendation(kind="Feature", description="high feature demand -> schedule top requested feature", priority=6))

        # --- revenue vs cost ---
        revenue = get("revenue")
        cost = get("infrastructure_cost")
        if revenue and cost:
            if revenue.delta_pct >= 10 and cost.delta_pct <= 5:
                recs.append(Recommendation(kind="Scale", description="revenue up while cost stable -> scale spend", priority=5))
            if cost.delta_pct >= 20 and (revenue is None or revenue.delta_pct < cost.delta_pct):
                issues.append(AnalyticsIssue(severity="warning", metric="infrastructure_cost", description=f"cost +{cost.delta_pct:.0f}% outpacing revenue"))
                recs.append(Recommendation(kind="Optimization", description="cost outpacing revenue -> optimize infra", priority=7))

        # --- overall health ---
        if any(i.severity == "critical" for i in issues):
            health = "critical"
        elif issues:
            health = "degraded"
        else:
            health = "good"
        if not signals and not issues:
            signals.append("no material telemetry change")

        summary = (
            f"{len(issues)} issue(s), {len(recs)} recommendation(s)"
            + (f" (source: {metrics_path})" if metrics_path else "")
        )
        return AnalyticsReport(
            project_id=project_id,
            health=health,
            summary=summary,
            signals=signals,
            issues=issues,
            recommendations=recs,
        )
