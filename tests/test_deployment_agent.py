"""Tests for the V5 Deployment Agent (release ladder + auto-rollback)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from factory.agents.deployment import DeploymentEngine
from factory.schemas.deployment import (
    RELEASE_ORDER,
    CanaryMetrics,
    GateResult,
    ReleaseStage,
)


def _all_gates_ok() -> list[GateResult]:
    return [GateResult(stage=s, passed=True, detail="ok") for s in RELEASE_ORDER]


class TestDeploymentEngine:
    def test_full_ladder_goes_live(self):
        decision = DeploymentEngine().deploy("p_x", _all_gates_ok())
        assert decision.status == "LIVE"
        assert decision.rolled_back_at is None
        assert len(decision.gates) == len(RELEASE_ORDER)

    def test_failed_smoke_rolls_back_early(self):
        gates = [GateResult(stage=ReleaseStage.STAGING_SMOKE, passed=False, detail="smoke fail")]
        decision = DeploymentEngine().deploy("p_x", gates)
        assert decision.status == "ROLLED_BACK"
        assert decision.rolled_back_at == ReleaseStage.STAGING_SMOKE
        assert "STAGING_SMOKE" in decision.rollback_reason

    def test_failed_security_gate_rolls_back(self):
        gates = _all_gates_ok()
        gates[1] = GateResult(stage=ReleaseStage.SECURITY_GATE, passed=False, detail="vuln")
        decision = DeploymentEngine().deploy("p_x", gates)
        assert decision.status == "ROLLED_BACK"
        assert decision.rolled_back_at == ReleaseStage.SECURITY_GATE

    def test_failed_perf_gate_rolls_back(self):
        gates = _all_gates_ok()
        gates[2] = GateResult(stage=ReleaseStage.PERF_GATE, passed=False, detail="p99 too high")
        decision = DeploymentEngine().deploy("p_x", gates)
        assert decision.status == "ROLLED_BACK"
        assert decision.rolled_back_at == ReleaseStage.PERF_GATE

    def test_canary_error_regression_rolls_back(self):
        decision = DeploymentEngine().deploy(
            "p_x",
            _all_gates_ok(),
            canary_metrics={
                "CANARY_1": CanaryMetrics(error_rate=0.12, error_baseline=0.01),
            },
        )
        assert decision.status == "ROLLED_BACK"
        assert decision.rolled_back_at == ReleaseStage.CANARY_1
        assert "error" in decision.rollback_reason

    def test_canary_latency_regression_rolls_back(self):
        decision = DeploymentEngine().deploy(
            "p_x",
            _all_gates_ok(),
            canary_metrics={
                "CANARY_5": CanaryMetrics(latency_pct_delta=35.0),
            },
        )
        assert decision.status == "ROLLED_BACK"
        assert decision.rolled_back_at == ReleaseStage.CANARY_5

    def test_canary_conversion_drop_rolls_back(self):
        decision = DeploymentEngine().deploy(
            "p_x",
            _all_gates_ok(),
            canary_metrics={
                "CANARY_25": CanaryMetrics(conversion_pct_delta=-20.0),
            },
        )
        assert decision.status == "ROLLED_BACK"
        assert decision.rolled_back_at == ReleaseStage.CANARY_25

    def test_healthy_canaries_finish_live(self):
        decision = DeploymentEngine().deploy(
            "p_x",
            _all_gates_ok(),
            canary_metrics={
                "CANARY_1": CanaryMetrics(error_rate=0.01, conversion_pct_delta=+2.0),
                "CANARY_100": CanaryMetrics(error_rate=0.02, conversion_pct_delta=+5.0),
            },
        )
        assert decision.status == "LIVE"


class TestDeploymentAgentRun:
    def _write_config(self, tmp_path: Path, gates: list[dict], metrics: dict | None = None) -> Path:
        cfg = {
            "project_id": "p_v5",
            "gates": gates,
            "canary_metrics": metrics or {},
        }
        p = tmp_path / "deployment_config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        return p

    def test_no_gates_fails_closed(self):
        decision = DeploymentEngine().deploy("p_x", [])
        assert decision.status == "ROLLED_BACK"
        assert "no gates" in decision.rollback_reason

    def test_run_writes_artifacts(self, tmp_path):
        from factory.agents.base import AgentInput
        from factory.agents.deployment import DeploymentEngine

        self._write_config(
            tmp_path,
            [{"stage": s.value, "passed": True, "detail": "ok"} for s in RELEASE_ORDER],
        )
        out = DeploymentEngine().run(
            AgentInput(
                agent="deployment",
                project_id="p_v5",
                task_id="deploy",
                goal="deploy",
                constraints=[],
                workdir=str(tmp_path),
                context={},
            )
        )
        assert out.status == "completed"
        assert (tmp_path / "deployments.json").exists()
        assert (tmp_path / "deployments.md").exists()
        data = json.loads((tmp_path / "deployments.json").read_text(encoding="utf-8"))
        assert data["status"] == "LIVE"
        assert len(data["gates"]) == len(RELEASE_ORDER)

    def test_run_missing_config_fails(self, tmp_path):
        from factory.agents.base import AgentInput
        from factory.agents.deployment import DeploymentEngine

        out = DeploymentEngine().run(
            AgentInput(
                agent="deployment",
                project_id="p_v5",
                task_id="deploy",
                goal="deploy",
                constraints=[],
                workdir=str(tmp_path),
                context={},
            )
        )
        assert out.status == "failed"


def test_cli_deploy_ok(tmp_path):
    cfg = tmp_path / "deployment_config.json"
    cfg.write_text(
        json.dumps(
            {
                "project_id": "p_cli",
                "gates": [{"stage": s.value, "passed": True, "detail": "ok"} for s in RELEASE_ORDER],
            }
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-m", "factory.cli", "deploy", str(cfg)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert out.returncode == 0, out.stderr
    assert "LIVE" in out.stdout
    assert (tmp_path / "deployments.json").exists()


def test_cli_deploy_rollback(tmp_path):
    cfg = tmp_path / "deployment_config.json"
    cfg.write_text(
        json.dumps(
            {
                "project_id": "p_cli",
                "gates": [{"stage": ReleaseStage.CANARY_5.value, "passed": False, "detail": "err"}],
                "canary_metrics": {},
            }
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-m", "factory.cli", "deploy", str(cfg)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert out.returncode != 0, out.stdout
    assert "ROLLED_BACK" in out.stdout


def test_cli_deploy_no_gates_fails_closed(tmp_path):
    cfg = tmp_path / "deployment_config.json"
    cfg.write_text(
        json.dumps(
            {
                "project_id": "p_cli",
                "gates": [],
                "canary_metrics": {},
            }
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-m", "factory.cli", "deploy", str(cfg)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert out.returncode != 0, out.stdout
    assert "Deployment failed" in out.stdout
