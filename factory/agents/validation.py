"""Validation Engine Agent (blueprint V4).

The Product Council gate between a scouted opportunity and a build decision:

    IDEA
     |-- evidence_score < threshold ....................... KILL
     v
    Cheap experiment (landing page / waitlist / pricing)
     |-- no conversion data yet ........................... TEST
     v
    conversion_rate < threshold ........................... KILL
     |-- conversion_rate >= threshold
     v
    BUILD

Roles are kept separate (blueprint §19/§20):
    ValidationEngine computes the evidence score (Opportunity Judge).
    DevilAdvocate raises objections (proof that this should NOT be built).
    JudgeEngine combines both into a final decision.

Deterministic by default: the rule-based judge mirrors the `Judge Score`
policy from blueprint §26 (decision + confidence + evidence dict) without
requiring an LLM; an OpenAI-compatible judge can be enabled via
OPENAI_API_KEY later.
"""
from __future__ import annotations

from pathlib import Path

from ..schemas.base import AgentOutput, Evidence
from ..schemas.opportunity import Opportunity
from ..schemas.validation import ValidationDecision
from .base import AgentInput

VALIDATIONS_JSON = "validations.json"
VALIDATIONS_MD = "validations.md"

DEFAULT_EVIDENCE_THRESHOLD = 0.40
DEFAULT_CONVERSION_THRESHOLD = 0.03  # 3% landing/waitlist conversion


def evidence_score_for(opp: Opportunity, evidence_target: int = 5) -> float:
    """Deterministic evidence score (blueprint §26).

    0.6 * strength of concrete evidence (summed pain evidence_count,
    capped at evidence_target) + 0.4 * hypothesis quality (weighted score).
    Synthetic candidates (evidence_count=0, recipe:// sources) score low.
    """
    evidence = sum(p.evidence_count for p in opp.pains)
    strength = min(1.0, evidence / max(1, evidence_target))
    quality = max(0.0, min(1.0, opp.score.total()))
    return round(0.6 * strength + 0.4 * quality, 3)


class DevilAdvocate:
    """Raises deterministic objections: prove this should NOT be built."""

    def run(self, opp: Opportunity) -> list[str]:
        objections: list[str] = []
        s = opp.score
        if s.competitor_weakness < 0.4:
            objections.append("已有较强的免费/低成本竞品（competitor_weakness 偏低）")
        if s.willingness_to_pay < 0.4:
            objections.append("用户付费意愿不足（willingness_to_pay 偏低）")
        if s.distribution_advantage < 0.3:
            objections.append("分发渠道没有优势（distribution_advantage 偏低）")
        if s.ai_advantage < 0.4:
            objections.append("AI 优势不明显，可能被大模型原生能力替代")
        if s.regulatory_risk > 0.5:
            objections.append("存在较高监管/合规风险")
        if s.build_cost > 0.3:
            objections.append("构建成本偏高，$5 级便宜实验可能失真")
        total_evidence = sum(p.evidence_count for p in opp.pains)
        synthetic = all(src.startswith("recipe://") for p in opp.pains for src in p.sources)
        if total_evidence == 0 and synthetic:
            objections.append("仅有合成示例证据，无任何真实市场信号")
        elif total_evidence == 0:
            objections.append("缺乏真实市场证据（evidence_count 为 0）")
        return objections


class JudgeEngine:
    """Deterministic judge (blueprint §26): decision + confidence + evidence."""

    def run(
        self,
        opp: Opportunity,
        evidence_score: float,
        evidence_threshold: float,
        conversion_rate: float | None,
        conversion_threshold: float,
        objections: list[str],
    ) -> ValidationDecision:
        reasons: list[str] = []
        gate_ok = evidence_score >= evidence_threshold

        # evidence gate
        if not gate_ok:
            decision = "KILL"
            reasons.append(
                f"evidence {evidence_score:.3f} < threshold {evidence_threshold:.2f}"
            )
            confidence = round(0.4 + 0.3 * evidence_score, 3)
            return ValidationDecision(
                opportunity_id=opp.opportunity_id,
                hypothesis=opp.hypothesis,
                evidence_score=evidence_score,
                evidence_threshold=evidence_threshold,
                evidence_gate="FAIL",
                conversion_rate=conversion_rate,
                conversion_threshold=conversion_threshold,
                conversion_gate=None,
                decision=decision,
                confidence=confidence,
                objections=objections,
                reasons=reasons,
            )

        reasons.append(f"evidence {evidence_score:.3f} >= threshold {evidence_threshold:.2f}")

        # conversion gate (cheap experiment)
        if conversion_rate is None:
            # no experiment data yet -> TEST
            confidence = round(0.55 + 0.25 * evidence_score, 3)
            return ValidationDecision(
                opportunity_id=opp.opportunity_id,
                hypothesis=opp.hypothesis,
                evidence_score=evidence_score,
                evidence_threshold=evidence_threshold,
                evidence_gate="PASS",
                conversion_rate=None,
                conversion_threshold=conversion_threshold,
                conversion_gate=None,
                decision="TEST",
                confidence=confidence,
                objections=objections,
                reasons=reasons + ["待跑便宜实验（landing page / waitlist）"],
            )

        conv_ok = conversion_rate >= conversion_threshold
        if conv_ok:
            decision = "BUILD"
            reasons.append(
                f"conversion {conversion_rate:.3f} >= threshold {conversion_threshold:.2f}"
            )
            confidence = round(0.6 + 0.25 * evidence_score + 0.15 * min(1.0, conversion_rate * 10), 3)
        else:
            decision = "KILL"
            reasons.append(
                f"conversion {conversion_rate:.3f} < threshold {conversion_threshold:.2f}"
            )
            confidence = round(0.4 + 0.2 * evidence_score, 3)

        # strong objections downgrade BUILD to TEST
        if decision == "BUILD" and len(objections) >= 3:
            decision = "TEST"
            reasons.append(f"{len(objections)} 条 devil's advocate 反对意见，降级为 TEST")

        return ValidationDecision(
            opportunity_id=opp.opportunity_id,
            hypothesis=opp.hypothesis,
            evidence_score=evidence_score,
            evidence_threshold=evidence_threshold,
            evidence_gate="PASS",
            conversion_rate=conversion_rate,
            conversion_threshold=conversion_threshold,
            conversion_gate="PASS" if conv_ok else "FAIL",
            decision=decision,
            confidence=confidence,
            objections=objections,
            reasons=reasons,
        )


class ValidationEngine:
    """V4: validate opportunity candidates into BUILD / TEST / KILL."""

    def __init__(
        self,
        evidence_threshold: float = DEFAULT_EVIDENCE_THRESHOLD,
        conversion_threshold: float = DEFAULT_CONVERSION_THRESHOLD,
    ) -> None:
        self.evidence_threshold = evidence_threshold
        self.conversion_threshold = conversion_threshold
        self._advocate = DevilAdvocate()
        self._judge = JudgeEngine()

    def validate(
        self,
        opp: Opportunity,
        conversion_rate: float | None = None,
    ) -> ValidationDecision:
        """Validate one opportunity; conversion_rate simulates cheap experiment."""
        score = evidence_score_for(opp)
        objections = self._advocate.run(opp)
        return self._judge.run(
            opp,
            score,
            self.evidence_threshold,
            conversion_rate,
            self.conversion_threshold,
            objections,
        )

    def run(self, task: AgentInput) -> AgentOutput:
        """Agent-entry contract: read opportunities.json, write validations."""
        from json import loads

        from ..schemas.base import AgentOutput as AO

        workdir = Path(task.workdir)
        opp_path = workdir / "opportunities.json"
        if not opp_path.exists():
            return AO(status="failed", summary=f"missing {opp_path}")
        candidates = [Opportunity.model_validate(d) for d in loads(opp_path.read_text(encoding="utf-8"))]
        conversions = task.context.get("conversion_rates", {})
        decisions = [
            self.validate(o, conversion_rate=conversions.get(o.opportunity_id))
            for o in candidates
        ]
        _write_validations(workdir, decisions)
        counts = _count(decisions)
        return AO(
            status="completed",
            summary=f"validated {len(decisions)} candidate(s): "
            f"{counts['BUILD']} BUILD / {counts['TEST']} TEST / {counts['KILL']} KILL",
            artifacts=[VALIDATIONS_JSON, VALIDATIONS_MD],
            evidence=[
                Evidence(
                    kind="validation",
                    detail=d.opportunity_id,
                    value=d.evidence_score,
                    meta={"decision": d.decision, "confidence": d.confidence},
                )
                for d in decisions
            ],
        )


def _count(decisions: list[ValidationDecision]) -> dict[str, int]:
    return {
        "BUILD": sum(1 for d in decisions if d.decision == "BUILD"),
        "TEST": sum(1 for d in decisions if d.decision == "TEST"),
        "KILL": sum(1 for d in decisions if d.decision == "KILL"),
    }


def _write_validations(workdir: Path, decisions: list[ValidationDecision]) -> None:
    json_path = workdir / VALIDATIONS_JSON
    md_path = workdir / VALIDATIONS_MD
    json_path.write_text(
        __import__("json").dumps([d.to_json_dict() for d in decisions], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(_validations_md(decisions), encoding="utf-8")


def _validations_md(decisions: list[ValidationDecision]) -> str:
    lines = [
        "# Validation Engine — 验证决策",
        "",
        "> 由自治软件工厂 Validation Engine（V4）生成：证据阈值 → 便宜实验 → 转化率阈值。",
        "",
        "| opportunity | evidence | gate | conversion | decision | confidence |",
        "|---|---|---|---|---|---|",
    ]
    for d in decisions:
        conv = "-" if d.conversion_rate is None else f"{d.conversion_rate:.3f}"
        lines.append(
            f"| {d.opportunity_id} | {d.evidence_score:.3f} | {d.evidence_gate} | "
            f"{conv} | **{d.decision}** | {d.confidence:.3f} |"
        )
    lines += ["", "### 决策明细", ""]
    for d in decisions:
        lines += [
            f"## {d.opportunity_id} — {d.decision}",
            "",
            f"- 假设: {d.hypothesis}",
            f"- evidence_score: {d.evidence_score:.3f} (threshold {d.evidence_threshold:.2f})",
            f"- conversion: {d.conversion_rate} (threshold {d.conversion_threshold:.2f})",
            f"- confidence: {d.confidence:.3f}",
            "",
            "反对意见（Devil's Advocate）:",
            "",
        ]
        for obj in d.objections:
            lines.append(f"- {obj}")
        lines += ["", "理由（Judge）:", ""]
        for r in d.reasons:
            lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines)
