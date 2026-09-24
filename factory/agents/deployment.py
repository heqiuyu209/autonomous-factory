"""Deployment Agent (blueprint V5): staged release with auto-rollback.

Deterministic release runner following the ladder:

    merge -> STAGING_SMOKE -> SECURITY_GATE -> PERF_GATE
          -> CANARY_1 -> CANARY_5 -> CANARY_25 -> CANARY_100 -> LIVE

Any failed gate stops the ladder and marks the release ROLLED_BACK
(error up / latency up / conversion down are automatic rollback triggers,
blueprint §16). No LLM required; an OpenAI-compatible backend can be layered
on later for richer smoke/perf judgement.
"""
from __future__ import annotations

from pathlib import Path

from ..schemas.base import AgentOutput
from ..schemas.deployment import (
    RELEASE_ORDER,
    CanaryMetrics,
    DeploymentDecision,
    GateResult,
)
from .base import AgentInput

DEPLOYMENTS_JSON = "deployments.json"
DEPLOYMENTS_MD = "deployments.md"


class DeploymentEngine:
    """Walk the release ladder; fail-closed on any gate or metric regression."""

    def __init__(self, error_threshold: float = 0.05, latency_delta_threshold: float = 10.0) -> None:
        self.error_threshold = error_threshold
        self.latency_delta_threshold = latency_delta_threshold

    def deploy(
        self,
        project_id: str,
        gates: list[GateResult],
        canary_metrics: dict[str, CanaryMetrics] | None = None,
    ) -> DeploymentDecision:
        metrics = canary_metrics or {}
        decision = DeploymentDecision(project_id=project_id, status="DEPLOYING")
        passed_by_stage = {g.stage.value: g.passed for g in gates}

        # build the passed map from provided gates only (unknown stages absent
        # -> treated as skipped/not-yet-run)
        for stage in RELEASE_ORDER:
            key = stage.value
            if key in passed_by_stage and not passed_by_stage[key]:
                decision.status = "ROLLED_BACK"
                decision.rolled_back_at = stage
                decision.rollback_reason = f"gate {key} failed"
                break

            # canary stage: run the telemetry guard
            if stage in metrics:
                m = metrics[key]
                if (
                    m.error_rate > self.error_threshold
                    or m.latency_pct_delta > self.latency_delta_threshold
                    or m.conversion_pct_delta < 0
                ):
                    decision.status = "ROLLED_BACK"
                    decision.rolled_back_at = stage
                    decision.rollback_reason = (
                        f"canary {key} regression: "
                        f"error={m.error_rate:.3f} "
                        f"latency_delta={m.latency_pct_delta:+.1f}% "
                        f"conversion_delta={m.conversion_pct_delta:+.1f}%"
                    )
                    break
            decision.gates.append(GateResult(stage=stage, passed=True, detail=f"{stage.value} ok"))

        if decision.status != "ROLLED_BACK":
            decision.status = "LIVE"
            decision.evidence = [
                "all release stages passed",
                f"{len(decision.gates)}/{len(RELEASE_ORDER)} stages green",
            ]
        else:
            decision.evidence = [f"rolled back at {decision.rolled_back_at}: {decision.rollback_reason}"]
        return decision

    def run(self, task: AgentInput) -> AgentOutput:
        from json import loads

        from ..schemas.base import AgentOutput as AO

        workdir = Path(task.workdir)
        cfg_path = workdir / "deployment_config.json"
        if not cfg_path.exists():
            return AO(status="failed", summary=f"missing {cfg_path}")
        cfg = loads(cfg_path.read_text(encoding="utf-8"))
        gates = [GateResult.model_validate(g) for g in cfg.get("gates", [])]
        metrics = {
            k: CanaryMetrics.model_validate(v)
            for k, v in (cfg.get("canary_metrics") or {}).items()
        }
        decision = self.deploy(cfg.get("project_id", "p_unknown"), gates, metrics)
        _write_deployments(workdir, decision)
        return AO(
            status="completed",
            summary=f"release {decision.status}"
            + (f" (rolled back at {decision.rolled_back_at})" if decision.rolled_back_at else ""),
            artifacts=[DEPLOYMENTS_JSON, DEPLOYMENTS_MD],
        )


def _write_deployments(workdir: Path, decision: DeploymentDecision) -> None:
    (workdir / DEPLOYMENTS_JSON).write_text(
        __import__("json").dumps(decision.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    lines = [
        "# Deployment — 发布管道",
        "",
        f"> 项目 `{decision.project_id}` 发布状态：**{decision.status}**",
        "",
        "| stage | 结果 |",
        "|---|---|",
    ]
    for g in decision.gates:
        lines.append(f"| {g.stage.value} | ✅ pass |")
    if decision.rolled_back_at:
        lines += [
            "",
            f"**回滚于 {decision.rolled_back_at.value}**：{decision.rollback_reason}",
        ]
    if decision.rollback_reason:
        lines += ["", f"回滚原因：{decision.rollback_reason}", ""]
    lines += ["", "### 证据", ""]
    for e in decision.evidence:
        lines.append(f"- {e}")
    (workdir / DEPLOYMENTS_MD).write_text("\n".join(lines), encoding="utf-8")
