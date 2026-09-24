"""Portfolio CEO Agent (blueprint V6): Build / Scale / Kill over N products.

The top of the factory is not a Planner but an Autonomous CEO (blueprint §1).
It does not write code; it owns the portfolio:

    discover opportunities (V3 scout)
    evaluate existing products (V4 validation / V5 deployment+analytics)
    allocate compute budget and coding agents
    kill bad experiments, increase investment in winners

Darwinian portfolio (blueprint §18):

    20 hypotheses -> validation -> 8 -> prototype -> 4 -> MVP -> 2
    -> real users -> 1 -> scale

Deterministic rule engine by default (mirrors the blueprint without needing
an LLM): reads the per-product state files that earlier stages produced and
emits a BUILD / SCALE / EXPERIMENT / HOLD / KILL action plus a budget weight.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..schemas.base import AgentOutput, Evidence
from ..schemas.portfolio import PortfolioAction, PortfolioReport
from .base import AgentInput

PORTFOLIO_JSON = "portfolio.json"
PORTFOLIO_MD = "portfolio.md"

ACTION_PRIORITY = {"KILL": 9, "SCALE": 8, "BUILD": 7, "EXPERIMENT": 5, "HOLD": 2}
ACTION_BUDGET = {"SCALE": 0.45, "BUILD": 0.30, "EXPERIMENT": 0.20, "HOLD": 0.05, "KILL": 0.0}


class PortfolioCEO:
    """V6: turn per-product state files into a portfolio-level decision."""

    def decide(self, product_dir: Path) -> PortfolioAction:
        """Decide the next action for ONE product directory."""
        product_id = product_dir.name
        analytics_path = product_dir / "analytics.json"
        deployment_path = product_dir / "deployments.json"
        validation_path = product_dir / "validations.json"

        sources: list[str] = []
        reasons: list[str] = []
        action: str | None = None

        # 1) analytics is the strongest signal (product is LIVE / MEASURING)
        if analytics_path.exists():
            sources.append("analytics.json")
            report = _read_analytics(analytics_path)
            action, extra = _decide_from_analytics(report)
            reasons += extra

        # 2) deployment outcome (rolled back releases are failures)
        if deployment_path.exists():
            sources.append("deployments.json")
            deploy = _read_deployment(deployment_path)
            status = deploy.get("status", "") if isinstance(deploy, dict) else ""
            if action in (None, "HOLD"):
                if status == "ROLLED_BACK":
                    action = "KILL"
                    reasons.append(f"release rolled back: {deploy.get('rollback_reason', '')}")
                elif status == "LIVE":
                    action = "EXPERIMENT"
                    reasons.append("live release needs real-user data -> run growth experiment")

        # 3) validation verdict (pre-build gates)
        if validation_path.exists():
            sources.append("validations.json")
            verdicts = _read_validations(validation_path)
            top = _top_validation(verdicts)
            if action in (None, "HOLD"):
                if top == "KILL":
                    action = "KILL"
                    reasons.append("validation gate said KILL")
                elif top == "BUILD":
                    action = "BUILD"
                    reasons.append("validation gate said BUILD -> start build")
                elif top == "TEST":
                    action = "EXPERIMENT"
                    reasons.append("validation gate said TEST -> run cheap experiment")

        if action is None:
            action = "HOLD"
            reasons.append("no state files yet -> hold for scout/validation")

        if not reasons:
            reasons.append(f"{product_id} has no actionable signals yet")

        return PortfolioAction(
            product_id=product_id,
            action=action,
            priority=ACTION_PRIORITY[action],
            budget_weight=ACTION_BUDGET[action],
            sources=sources,
            reasons=reasons,
        )

    def run(self, task: AgentInput) -> AgentOutput:
        """Agent-entry contract: scan workdir/<product>/ state files,
        write portfolio.json + portfolio.md (in out_dir when provided)."""
        root = Path(task.workdir)
        raw_out = task.context.get("out_dir") if task.context else None
        out_dir = Path(raw_out) if raw_out else root
        out_dir.mkdir(parents=True, exist_ok=True)
        products = [
            p
            for p in sorted(root.iterdir())
            if p.is_dir()
            and not p.name.startswith(".")
            and _has_state(p)
        ]
        if not products:
            return AgentOutput(status="failed", summary=f"no product directories under {root}")

        actions = [self.decide(p) for p in products]
        actions.sort(key=lambda a: (-a.priority, a.product_id))
        allocation = _allocate_budget(actions)
        for a in actions:
            a.budget_weight = allocation.get(a.product_id, 0.0)

        report = PortfolioReport(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            products=actions,
            summary=_summary(actions),
            allocation=allocation,
        )
        _write_portfolio(out_dir, report)

        counts = _counts(actions)
        return AgentOutput(
            status="completed",
            summary=f"portfolio: {len(actions)} product(s) -> "
            + " / ".join(f"{k} {v}" for k, v in sorted(counts.items()) if v),
            artifacts=[PORTFOLIO_JSON, PORTFOLIO_MD],
            evidence=[
                Evidence(
                    kind="portfolio",
                    detail=a.product_id,
                    value=float(a.priority),
                    meta={"action": a.action, "budget_weight": a.budget_weight},
                )
                for a in actions
            ],
        )


_STATE_FILES = ("analytics.json", "deployments.json", "validations.json")


def _has_state(product_dir: Path) -> bool:
    """A product counts when it carries at least one state file or any file."""
    if any((product_dir / name).exists() for name in _STATE_FILES):
        return True
    return any(p.is_file() for p in product_dir.iterdir())


def _read_analytics(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, list):
            return data[-1] if data else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _read_deployment(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _read_validations(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return [data] if isinstance(data, dict) else []
    except (ValueError, OSError):
        return []


def _top_validation(verdicts: list[dict]) -> str:
    """Highest-severity verdict wins: KILL > TEST > BUILD."""
    seen = {v.get("decision") for v in verdicts}
    for verdict in ("KILL", "TEST", "BUILD"):
        if verdict in seen:
            return verdict
    return "HOLD"


def _decide_from_analytics(report: dict) -> tuple[str, list[str]]:
    """Analytics -> action. Strongest recommendation wins (Kill > Scale >
    Experiment); without explicit recommendations fall back to health."""
    reasons: list[str] = []
    recs = report.get("recommendations", []) if isinstance(report, dict) else []
    kinds = [r.get("kind") for r in recs if isinstance(r, dict)]
    if "Kill" in kinds:
        return "KILL", reasons + [f"analytics recommended Kill: {_first_desc(recs, 'Kill')}"]
    if "Scale" in kinds:
        return "SCALE", reasons + [f"analytics recommended Scale: {_first_desc(recs, 'Scale')}"]
    if "Experiment" in kinds:
        return "EXPERIMENT", reasons + [f"analytics recommended Experiment: {_first_desc(recs, 'Experiment')}"]
    if "Optimization" in kinds or "Bug" in kinds or "Feature" in kinds:
        return "EXPERIMENT", reasons + ["analytics recommended Optimization/Bug/Feature work"]

    health = report.get("health") if isinstance(report, dict) else None
    if health == "critical":
        return "KILL", reasons + ["analytics health critical"]
    if health == "degraded":
        return "EXPERIMENT", reasons + ["analytics health degraded -> run experiment"]
    if health == "good":
        return "SCALE", reasons + ["analytics health good -> double down"]
    return "HOLD", reasons + ["analytics present but no verdict"]


def _first_desc(recs: list, kind: str) -> str:
    for r in recs:
        if isinstance(r, dict) and r.get("kind") == kind:
            return str(r.get("description", ""))
    return ""


def _allocate_budget(actions: list[PortfolioAction]) -> dict[str, float]:
    raw = {a.product_id: ACTION_BUDGET[a.action] for a in actions}
    total = sum(raw.values())
    if total <= 0:
        share = 1.0 / max(1, len(actions))
        return {pid: round(share, 3) for pid in raw}
    return {pid: round(w / total, 3) for pid, w in raw.items()}


def _counts(actions: list[PortfolioAction]) -> dict[str, int]:
    return {kind: sum(1 for a in actions if a.action == kind) for kind in ACTION_PRIORITY}


def _summary(actions: list[PortfolioAction]) -> str:
    counts = _counts(actions)
    total = len(actions)
    live = [a for a in actions if a.action in ("SCALE", "EXPERIMENT")]
    kill = counts["KILL"]
    head = f"{total} product(s) in portfolio"
    if live:
        head += f"; {len(live)} get follow-on investment"
    if kill:
        head += f"; {kill} killed (budget freed)"
    return head


def _write_portfolio(out_dir: Path, report: PortfolioReport) -> None:
    (out_dir / PORTFOLIO_JSON).write_text(
        json.dumps(report.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    lines = [
        "# Portfolio CEO — 组合决策",
        "",
        "> 由自治软件工厂 Portfolio CEO（V6）生成：对组合内每个产品给出 Build / Scale / Experiment / Hold / Kill 决策与预算分配。",
        "",
        f"**{report.summary}**",
        "",
        "| product | action | priority | budget | 依据 |",
        "|---|---|---|---|---|",
    ]
    for a in report.products:
        lines.append(
            f"| {a.product_id} | **{a.action}** | {a.priority} | {a.budget_weight:.3f} | "
            f"{', '.join(a.sources) if a.sources else '-'} |"
        )
    lines += ["", "### 决策明细", ""]
    for a in report.products:
        lines += [f"## {a.product_id} — {a.action}", ""]
        for r in a.reasons:
            lines.append(f"- {r}")
        lines.append("")
    lines += ["", "### 预算分配", "", "| product | weight |", "|---|---|"]
    for pid, w in sorted(report.allocation.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {pid} | {w:.3f} |")
    (out_dir / PORTFOLIO_MD).write_text("\n".join(lines), encoding="utf-8")
