"""Tests for the V5 Analytics Agent (telemetry -> next iteration)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from factory.agents.analytics import AnalyticsEngine
from factory.schemas.analytics import MetricSample


def _samples(pairs: dict[str, tuple[float, float]]) -> list[MetricSample]:
    return [MetricSample(metric=k, value=v, delta_pct=d) for k, (v, d) in pairs.items()]


class TestAnalyticsEngine:
    def test_healthy_no_issues(self):
        report = AnalyticsEngine().analyze(
            _samples({"traffic": (1000.0, 5.0), "errors": (0.005, 0.0)})
        )
        assert report.health == "good"
        assert report.issues == []

    def test_critical_error_rate(self):
        report = AnalyticsEngine().analyze(_samples({"errors": (0.08, 10.0)}))
        assert report.health == "critical"
        assert any(i.severity == "critical" for i in report.issues)
        assert any(r.kind == "Bug" and r.priority == 10 for r in report.recommendations)

    def test_warning_error_rate(self):
        report = AnalyticsEngine().analyze(_samples({"errors": (0.03, 5.0)}))
        assert report.health == "degraded"
        assert any(r.kind == "Bug" for r in report.recommendations)

    def test_traffic_growth_scales(self):
        report = AnalyticsEngine().analyze(_samples({"traffic": (2000.0, 25.0)}))
        assert any(r.kind == "Scale" for r in report.recommendations)

    def test_traffic_drop_triggers_experiment(self):
        report = AnalyticsEngine().analyze(_samples({"traffic": (500.0, -30.0)}))
        assert report.health == "degraded"
        assert any(r.kind == "Experiment" for r in report.recommendations)

    def test_low_retention_optimization(self):
        report = AnalyticsEngine().analyze(_samples({"retention": (0.20, -2.0)}))
        assert any(r.kind == "Optimization" for r in report.recommendations)

    def test_activation_decline_experiment(self):
        report = AnalyticsEngine().analyze(_samples({"activation": (0.10, -18.0)}))
        assert any(r.kind == "Experiment" for r in report.recommendations)

    def test_feature_requests_schedule_feature(self):
        report = AnalyticsEngine().analyze(_samples({"feature_requests": (50.0, 20.0)}))
        assert any(r.kind == "Feature" for r in report.recommendations)

    def test_support_surge_bug(self):
        report = AnalyticsEngine().analyze(_samples({"support_tickets": (30.0, 40.0)}))
        assert any(r.kind == "Bug" for r in report.recommendations)

    def test_cost_outpacing_revenue(self):
        report = AnalyticsEngine().analyze(
            _samples({"revenue": (100.0, 5.0), "infrastructure_cost": (80.0, 30.0)})
        )
        assert any(r.kind == "Optimization" for r in report.recommendations)

    def test_empty_samples_still_reports(self):
        report = AnalyticsEngine().analyze([])
        assert report.health == "good"
        assert report.signals == ["no material telemetry change"]


def test_cli_analyze(tmp_path):
    metrics = tmp_path / "metrics.json"
    metrics.write_text(
        json.dumps(
            [
                {"metric": "errors", "value": 0.06, "delta_pct": 20.0},
                {"metric": "traffic", "value": 1000.0, "delta_pct": 30.0},
            ]
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-m", "factory.cli", "analyze", str(metrics)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert out.returncode == 0, out.stderr
    assert "critical" in out.stdout
    assert (tmp_path / "analytics.json").exists()
    assert (tmp_path / "analytics.md").exists()
