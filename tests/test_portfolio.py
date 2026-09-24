"""V6 Portfolio CEO tests: Build / Scale / Experiment / Hold / Kill decisions
built from per-product state files (validations / deployments / analytics)."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from factory.agents.portfolio import PortfolioCEO
from factory.cli import app
from factory.schemas.portfolio import PortfolioAction

runner = CliRunner()


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _validation(decision: str) -> dict:
    return [
        {
            "opportunity_id": "opp_1",
            "hypothesis": "h",
            "evidence_score": 0.5,
            "evidence_threshold": 0.4,
            "evidence_gate": "PASS",
            "conversion_rate": 0.08,
            "conversion_threshold": 0.03,
            "conversion_gate": "PASS",
            "decision": decision,
            "confidence": 0.7,
            "objections": [],
            "reasons": [],
        }
    ]


def _deployment(status: str, rollback_reason: str = "") -> dict:
    return {
        "project_id": "p",
        "status": status,
        "gates": [],
        "canary_metrics": {},
        "rolled_back_at": "CANARY_1" if status == "ROLLED_BACK" else None,
        "rollback_reason": rollback_reason,
        "evidence": [],
    }


def _analytics(health: str, kinds: list[str] | None = None) -> dict:
    return {
        "project_id": "p",
        "health": health,
        "summary": "s",
        "signals": [],
        "issues": [],
        "recommendations": (
            [{"kind": k, "description": f"rec {k}", "priority": 5} for k in kinds] if kinds else []
        ),
    }


def test_decide_no_state_files_hold(tmp_path: Path):
    action = PortfolioCEO().decide(tmp_path / "p_empty")
    assert isinstance(action, PortfolioAction)
    assert action.action == "HOLD"
    assert action.priority == 2
    assert action.sources == []


def test_decide_validation_build(tmp_path: Path):
    _write_json(tmp_path / "p1" / "validations.json", _validation("BUILD"))
    action = PortfolioCEO().decide(tmp_path / "p1")
    assert action.action == "BUILD"
    assert action.priority == 7
    assert "validations.json" in action.sources


def test_decide_validation_kill(tmp_path: Path):
    _write_json(tmp_path / "p1" / "validations.json", _validation("KILL"))
    assert PortfolioCEO().decide(tmp_path / "p1").action == "KILL"


def test_decide_validation_test_becomes_experiment(tmp_path: Path):
    _write_json(tmp_path / "p1" / "validations.json", _validation("TEST"))
    action = PortfolioCEO().decide(tmp_path / "p1")
    assert action.action == "EXPERIMENT"


def test_decide_deployment_live_experiment(tmp_path: Path):
    _write_json(tmp_path / "p1" / "deployments.json", _deployment("LIVE"))
    assert PortfolioCEO().decide(tmp_path / "p1").action == "EXPERIMENT"


def test_decide_deployment_rolled_back_kill(tmp_path: Path):
    _write_json(
        tmp_path / "p1" / "deployments.json",
        _deployment("ROLLED_BACK", "canary CANARY_1 regression"),
    )
    action = PortfolioCEO().decide(tmp_path / "p1")
    assert action.action == "KILL"
    assert any("rolled back" in r for r in action.reasons)


def test_decide_analytics_scale(tmp_path: Path):
    _write_json(tmp_path / "p1" / "analytics.json", _analytics("good", ["Scale"]))
    action = PortfolioCEO().decide(tmp_path / "p1")
    assert action.action == "SCALE"
    assert action.priority == 8


def test_decide_analytics_critical_kill(tmp_path: Path):
    _write_json(tmp_path / "p1" / "analytics.json", _analytics("critical"))
    assert PortfolioCEO().decide(tmp_path / "p1").action == "KILL"


def test_decide_analytics_wins_over_validation(tmp_path: Path):
    # analytics says SCALE even though validation said KILL
    _write_json(tmp_path / "p1" / "analytics.json", _analytics("good", ["Scale"]))
    _write_json(tmp_path / "p1" / "validations.json", _validation("KILL"))
    action = PortfolioCEO().decide(tmp_path / "p1")
    assert action.action == "SCALE"
    assert "analytics.json" in action.sources


def test_decide_optimization_becomes_experiment(tmp_path: Path):
    _write_json(tmp_path / "p1" / "analytics.json", _analytics("degraded", ["Optimization"]))
    assert PortfolioCEO().decide(tmp_path / "p1").action == "EXPERIMENT"


def test_allocate_budget_normalizes(tmp_path: Path):
    from factory.agents.base import AgentInput

    _write_json(tmp_path / "p1" / "analytics.json", _analytics("good", ["Scale"]))
    _write_json(tmp_path / "p2" / "validations.json", _validation("BUILD"))
    _write_json(tmp_path / "p3" / "analytics.json", _analytics("degraded", ["Experiment"]))
    out = PortfolioCEO().run(
        AgentInput(
            agent="portfolio",
            project_id="portfolio",
            task_id="portfolio",
            goal="decide portfolio",
            constraints=[],
            workdir=str(tmp_path),
        )
    )
    assert out.status == "completed", out.summary
    report = json.loads((tmp_path / "portfolio.json").read_text(encoding="utf-8"))
    total = sum(report["allocation"].values())
    assert total > 0.99 and total < 1.01
    # Scale gets the largest slice
    assert report["allocation"]["p1"] > report["allocation"]["p2"] > report["allocation"]["p3"]


def test_run_writes_portfolio_artifacts(tmp_path: Path):
    _write_json(tmp_path / "p1" / "analytics.json", _analytics("good", ["Scale"]))
    _write_json(tmp_path / "p2" / "validations.json", _validation("BUILD"))
    _write_json(tmp_path / "p3" / "deployments.json", _deployment("ROLLED_BACK", "gate failed"))
    from factory.agents.base import AgentInput

    out = PortfolioCEO().run(
        AgentInput(
            agent="portfolio",
            project_id="portfolio",
            task_id="portfolio",
            goal="decide portfolio",
            constraints=[],
            workdir=str(tmp_path),
        )
    )
    assert out.status == "completed", out.summary
    assert "SCALE 1" in out.summary and "BUILD 1" in out.summary and "KILL 1" in out.summary
    json_file = tmp_path / "portfolio.json"
    md_file = tmp_path / "portfolio.md"
    assert json_file.exists() and md_file.exists()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(data["products"]) == 3
    by_id = {p["product_id"]: p["action"] for p in data["products"]}
    assert by_id == {"p1": "SCALE", "p2": "BUILD", "p3": "KILL"}
    assert "Portfolio CEO" in md_file.read_text(encoding="utf-8")


def test_run_no_products_fails(tmp_path: Path):
    from factory.agents.base import AgentInput

    out = PortfolioCEO().run(
        AgentInput(
            agent="portfolio",
            project_id="portfolio",
            task_id="portfolio",
            goal="decide portfolio",
            constraints=[],
            workdir=str(tmp_path / "empty"),
        )
    )
    assert out.status == "failed"


def test_cli_portfolio_command(tmp_path: Path):
    _write_json(tmp_path / "port" / "p1" / "analytics.json", _analytics("good", ["Scale"]))
    _write_json(tmp_path / "port" / "p2" / "validations.json", _validation("KILL"))
    out = runner.invoke(app, ["portfolio", str(tmp_path / "port")])
    assert out.exit_code == 0, out.output
    assert (tmp_path / "port" / "portfolio.json").exists()
    assert "SCALE 1" in out.output and "KILL 1" in out.output


def test_cli_portfolio_missing_dir(tmp_path: Path):
    out = runner.invoke(app, ["portfolio", str(tmp_path / "nope")])
    assert out.exit_code == 1
    assert "not found" in out.output
