"""Market Scout Agent (blueprint V3).

Turns a market direction / query into a ranked list of opportunity
candidates (hypothesis + pains + score), the input contract of V4's
Validation Engine:

    market query -> [Scout] -> opportunities (PENDING) -> [V4] -> decision

Two backends (same pattern as CoderAgent/PMAgent/ArchitectAgent):
    RecipeBackend  - deterministic in-process candidate generator (no API key).
                     Used for demos / E2E tests without any external call.
                     Candidates are explicitly marked as synthetic examples.
    OpenAIBackend  - optional real-LLM scout via an OpenAI-compatible API.
                     Enabled only when OPENAI_API_KEY is present.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..policy import PolicyEngine
from ..schemas.base import AgentOutput
from ..schemas.opportunity import Opportunity, OpportunityScore, PainPoint
from .base import AgentInput

if TYPE_CHECKING:  # pragma: no cover
    from ..sources import Fetcher, Signal

OPPORTUNITIES_JSON = "opportunities.json"
OPPORTUNITIES_MD = "opportunities.md"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _slug(query: str) -> str:
    """Deterministic safe project id derived from a market query."""
    words = _SLUG_RE.sub("_", query.strip().lower()).strip("_")
    words = words[:40].rstrip("_")
    return f"p_{words}" if words else "p_market"


def _synthetic_opportunity(query: str, sources: list[str]) -> Opportunity:
    """Deterministic example candidate (explicitly not real market research)."""
    slug = _slug(query)
    src = sources or ["recipe://synthetic"]
    return Opportunity(
        opportunity_id=f"opp_{slug}",
        hypothesis=f"提供一个面向「{query}」的轻量自动化产品，让用户以低成本获得核心价值",
        pains=[
            PainPoint(
                pain_id=f"pain_{slug}_1",
                persona="target user",
                problem=f"「{query}」相关工作依赖手工完成，耗时且易错",
                frequency="daily",
                severity=0.7,
                current_solution="手工流程 / 通用工具拼凑",
                willingness_to_pay=0.5,
                evidence_count=0,
                sources=list(src),
            ),
            PainPoint(
                pain_id=f"pain_{slug}_2",
                persona="power user",
                problem=f"现有方案对「{query}」场景适配差，配置复杂",
                frequency="weekly",
                severity=0.5,
                current_solution="自建脚本 / 外包",
                willingness_to_pay=0.4,
                evidence_count=0,
                sources=list(src),
            ),
        ],
        score=OpportunityScore(
            pain_severity=0.6,
            frequency=0.6,
            willingness_to_pay=0.5,
            market_size=0.5,
            search_demand=0.4,
            competitor_weakness=0.5,
            ai_advantage=0.6,
            distribution_advantage=0.4,
            build_cost=0.05,
            acquisition_difficulty=0.1,
            regulatory_risk=0.05,
            competition_risk=0.2,
        ),
        decision="PENDING",
    )


def _opportunities_md(opps: list[Opportunity]) -> str:
    lines = [
        "# Market Scout — 机会候选",
        "",
        "> 由自治软件工厂 Market Scout Agent 生成（RecipeBackend，确定性示例数据）。",
        "> 注意：以下候选为确定性示例，非真实市场调研；设置 OPENAI_API_KEY 后可扫描真实来源。",
        "",
    ]
    for opp in opps:
        lines += [
            f"## {opp.opportunity_id} — 假设",
            "",
            f"- 假设: {opp.hypothesis}",
            f"- 总分: {opp.score.total()}",
            f"- 决策: {opp.decision}",
            "",
            "### 痛点",
            "",
        ]
        for pain in opp.pains:
            lines.append(
                f"- {pain.pain_id} [{pain.severity:.1f}] {pain.persona}: {pain.problem}"
            )
            if pain.sources:
                lines.append(f"  - sources: {', '.join(pain.sources)}")
        lines.append("")
    return "\n".join(lines)


def _write_opportunities(workdir: Path, opps: list[Opportunity]) -> None:
    json_path = workdir / OPPORTUNITIES_JSON
    md_path = workdir / OPPORTUNITIES_MD
    json_path.write_text(
        json.dumps(
            [o.model_dump(mode="json") for o in opps],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_opportunities_md(opps), encoding="utf-8")


def _opportunity_from_signals(query: str, signals: list[Signal], sources: list[str]) -> Opportunity:
    """Build one candidate whose pains cite real fetched evidence."""
    slug = _slug(query)
    src_tags = sources or ["web"]
    pains = []
    for i, sig in enumerate(signals[:5], start=1):
        pains.append(
            PainPoint(
                pain_id=f"pain_{slug}_{i}",
                persona=sig.source,
                problem=f"{sig.title} — {sig.snippet[:120]}".strip(" —"),
                frequency="unknown",
                severity=0.5,
                current_solution="existing tooling",
                willingness_to_pay=0.4,
                evidence_count=1,
                sources=[sig.url],
            )
        )
    return Opportunity(
        opportunity_id=f"opp_{slug}",
        hypothesis=f"基于 {len(signals)} 条 {', '.join(src_tags)} 真实信号，「{query}」存在未被充分满足的需求，值得验证",
        pains=pains,
        score=OpportunityScore(
            pain_severity=0.6,
            frequency=0.5,
            willingness_to_pay=0.4,
            market_size=0.5,
            search_demand=0.5,
            competitor_weakness=0.5,
            ai_advantage=0.6,
            distribution_advantage=0.4,
            build_cost=0.05,
            acquisition_difficulty=0.1,
            regulatory_risk=0.05,
            competition_risk=0.2,
        ),
        decision="PENDING",
    )


class RecipeBackend:
    """Deterministic opportunity-candidate generator (no API key)."""

    name = "recipe"

    def run(self, task: AgentInput) -> AgentOutput:
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        opps = [_synthetic_opportunity(task.goal, task.constraints)]
        _write_opportunities(workdir, opps)
        return AgentOutput(
            status="completed",
            summary=f"scouted {len(opps)} opportunity candidate(s) for: {task.goal[:80]}",
            artifacts=[OPPORTUNITIES_JSON, OPPORTUNITIES_MD],
        )


class WebBackend:
    """Market-scout backend backed by real public sources (reddit/github).

    Fetches evidence from public JSON APIs; on total fetch failure it
    degrades to the deterministic RecipeBackend so the CLI never hard-fails.
    """

    name = "web"

    def __init__(self, fetchers: dict[str, Fetcher] | None = None, policy=None):
        from ..sources import SOURCE_FETCHERS, SOURCE_HOSTS

        self._fetchers = fetchers or dict(SOURCE_FETCHERS)
        self._source_hosts = dict(SOURCE_HOSTS)
        self._policy = policy or PolicyEngine()

    def run(self, task: AgentInput) -> AgentOutput:
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        wanted = [s for s in task.constraints if s in self._fetchers]
        if not wanted:
            wanted = list(self._fetchers) if not task.constraints else []
        signals: list[Signal] = []
        for source in wanted:
            # Capability gate: the market-scout role may only contact its
            # granted hosts. An explicit PolicyViolation fails the scout
            # (fail-closed) instead of silently reaching an unknown host.
            host = self._source_hosts.get(source)
            if host is not None:
                self._policy.check_internet("market-scout", host)
            try:
                signals.extend(self._fetchers[source](task.goal, limit=5))
            except Exception:  # noqa: BLE001 - a source must never break the scout
                continue
        if not signals:
            opps = [_synthetic_opportunity(task.goal, wanted)]
            _write_opportunities(workdir, opps)
            return AgentOutput(
                status="completed",
                summary=(
                    f"web fetch returned no signals for: {task.goal[:60]}; "
                    f"degraded to recipe candidates ({', '.join(wanted)})"
                ),
                artifacts=[OPPORTUNITIES_JSON, OPPORTUNITIES_MD],
            )
        opps = [_opportunity_from_signals(task.goal, signals, wanted)]
        _write_opportunities(workdir, opps)
        return AgentOutput(
            status="completed",
            summary=f"web-scouted {len(signals)} signal(s) from {', '.join(wanted)} for: {task.goal[:60]}",
            artifacts=[OPPORTUNITIES_JSON, OPPORTUNITIES_MD],
        )


class OpenAIBackend:
    """Optional real-LLM market scout (OpenAI-compatible).

    Requires OPENAI_API_KEY; otherwise MarketScoutAgent uses RecipeBackend.
    """

    name = "openai"

    def __init__(self, model: str | None = None):
        import openai  # lazy import; optional dependency

        self._client = openai.OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
        self._model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def run(self, task: AgentInput) -> AgentOutput:
        system = (
            "You are a market scout. Given a market direction, produce a JSON "
            "array of opportunity candidates. Each item must have keys: "
            "opportunity_id, hypothesis, pains (list of objects with pain_id, "
            "persona, problem, severity 0-1, willingness_to_pay 0-1, sources), "
            "and score fields (pain_severity, frequency, willingness_to_pay, "
            "market_size, search_demand, competitor_weakness, ai_advantage, "
            "distribution_advantage, build_cost, acquisition_difficulty, "
            "regulatory_risk, competition_risk), decision='PENDING'. "
            "Output ONLY valid JSON."
        )
        user = f"Market direction: {task.goal}\nData source hints: {task.constraints or 'none'}"
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
            )
            content = resp.choices[0].message.content if resp.choices else None
        except Exception as exc:
            return AgentOutput(status="failed", summary=f"LLM backend error: {exc!r}")
        if not content:
            return AgentOutput(status="failed", summary="LLM returned empty candidates")
        try:
            data = json.loads(content)
            opps = [Opportunity.model_validate(item) for item in data]
        except Exception as exc:
            return AgentOutput(status="failed", summary=f"LLM output not parseable: {exc!r}")
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        json_path = workdir / OPPORTUNITIES_JSON
        md_path = workdir / OPPORTUNITIES_MD
        json_path.write_text(
            json.dumps(
                [o.model_dump(mode="json") for o in opps],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        md_path.write_text(_opportunities_md(opps), encoding="utf-8")
        return AgentOutput(
            status="completed",
            summary=f"LLM scouted {len(opps)} candidate(s)",
            artifacts=[OPPORTUNITIES_JSON, OPPORTUNITIES_MD],
        )


class MarketScoutAgent:
    """Agent facade that picks the best available backend.

    Explicit `backend` wins; otherwise OPENAI_API_KEY enables the LLM
    backend, and --backend web (via CLI) or a WebBackend instance routes
    to real public-source fetching.
    """

    def __init__(self, backend=None):
        self.backend = backend or self._auto_backend()

    @staticmethod
    def _auto_backend():
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIBackend()
        return RecipeBackend()

    def run(self, task: AgentInput) -> AgentOutput:
        return self.backend.run(task)


__all__ = [
    "MarketScoutAgent",
    "OpenAIBackend",
    "RecipeBackend",
    "WebBackend",
    "_opportunities_md",
    "_slug",
]
