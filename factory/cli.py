"""Factory CLI.

Usage:
    factory init-db
    factory status <project_id>
    factory run <graph.json> [--prd prd.md] [--seed-bug/--no-seed-bug]
    factory demo
    factory policy <agent>
"""
from __future__ import annotations

from pathlib import Path

import typer

from .db import init_db
from .policy import PolicyEngine
from .schemas.task_graph import TaskGraph
from .state_machine import StateMachineError
from .workflows import DevelopmentWorkflow

app = typer.Typer(help="Autonomous Software Factory - V1 core.")

_DEMO_DIR = Path(__file__).resolve().parent.parent / "examples" / "sample_project"


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the factory database (default: local ./factory.db)."""
    init_db()
    typer.echo("Database ready.")


@app.command("status")
def status_cmd(project_id: str) -> None:
    """Show durable state of a project."""
    from json import dumps

    typer.echo(dumps(DevelopmentWorkflow.status(project_id), indent=2, ensure_ascii=False))


@app.command()
def run(
    graph: Path = typer.Argument(..., help="path to task_graph.json/yaml"),
    prd: Path | None = typer.Option(None, "--prd", help="path to PRD markdown"),
    seed_bug: bool = typer.Option(True, "--seed-bug/--no-seed-bug"),
) -> None:
    """Execute a project from its task graph."""
    g = TaskGraph.load(graph)
    wf = DevelopmentWorkflow()
    wf.plan(g.project_id, g.name, str(prd) if prd else None, str(graph))
    report = wf.build(g.project_id, g, seed_bug=seed_bug)
    _print_report(report, g.project_id)
    # Exit code is the CI contract: only a fully executed graph is 0.
    # Any BLOCKED/partial outcome must be visible to scripts.
    if report.get("summary", {}).get("state") != "DONE":
        typer.echo(f"ERROR: build did not complete ({report['summary'].get('state')})")
        raise typer.Exit(1)


@app.command()
def demo() -> None:
    """Run the bundled sample project end-to-end (with a seeded bug that the
    pipeline must catch and repair)."""
    graph_path = _DEMO_DIR / "task_graph.json"
    prd_path = _DEMO_DIR / "prd.md"
    if not (graph_path.exists() and prd_path.exists()):
        typer.echo(f"sample project not found at {_DEMO_DIR}")
        raise typer.Exit(1)
    run(graph_path, prd=prd_path)


@app.command("promote")
def promote_cmd(project_id: str) -> None:
    """Promote a fully-built, fully-reviewed project to PRODUCTION."""
    from json import dumps

    try:
        res = DevelopmentWorkflow().promote(project_id)
    except StateMachineError as exc:
        typer.echo(f"promote refused: {exc}")
        raise typer.Exit(1) from None
    typer.echo(dumps(res, indent=2, ensure_ascii=False))
    if not res.get("exists"):
        raise typer.Exit(1)


@app.command()
def policy(agent: str) -> None:
    """Show the granted capability set for an agent role."""
    engine = PolicyEngine()
    s = engine.summary(agent)
    for k, v in s.items():
        typer.echo(f"{k:12}: {v}")


def _plan_pipeline(
    pid: str,
    workdir: Path,
    goal: str,
    constraints: list[str],
    acceptance: list[str],
) -> None:
    """Shared PM -> Architect pipeline used by `plan` and `scout --plan`."""
    from .agents.architect import ArchitectAgent
    from .agents.base import AgentInput
    from .agents.pm import PMAgent

    workdir.mkdir(parents=True, exist_ok=True)

    pm_out = PMAgent().run(
        AgentInput(
            agent="pm",
            project_id=pid,
            task_id="plan",
            goal=goal,
            constraints=constraints,
            acceptance_criteria=acceptance,
            workdir=str(workdir),
        )
    )
    if pm_out.status != "completed":
        typer.echo(f"PM failed: {pm_out.summary}")
        raise typer.Exit(1)

    arch_out = ArchitectAgent().run(
        AgentInput(
            agent="architect",
            project_id=pid,
            task_id="plan",
            goal=goal,
            workdir=str(workdir),
        )
    )
    if arch_out.status != "completed":
        typer.echo(f"Architect failed: {arch_out.summary}")
        raise typer.Exit(1)

    typer.echo(f"PRD        : {workdir / 'prd.md'}")
    typer.echo(f"Task graph : {workdir / 'task_graph.json'}")
    typer.echo("Next step: factory run <task_graph.json> --prd <prd.md>")


@app.command()
def plan(
    goal: str = typer.Argument(..., help="problem statement / goal"),
    out_dir: Path = typer.Option(
        Path(__file__).resolve().parent.parent / "examples" / "v2_plans",
        "--out-dir",
        help="output directory for PRD and task graph",
    ),
    project_id: str | None = typer.Option(None, "--project-id", help="override project id"),
    constraint: list[str] = typer.Option([], "--constraint", help="repeatable constraint"),
    acceptance: list[str] = typer.Option([], "--acceptance", help="repeatable acceptance criterion"),
) -> None:
    """V2: turn a problem statement into PRD + task graph (PM -> Architect)."""
    from .agents.scout import _slug

    pid = project_id or _slug(goal)
    _plan_pipeline(pid, out_dir / pid, goal, constraint, acceptance)


@app.command()
def scout(
    query: str = typer.Argument(..., help="market direction / query to scout"),
    out_dir: Path = typer.Option(
        Path(__file__).resolve().parent.parent / "examples" / "v3_scouts",
        "--out-dir",
        help="output directory for opportunity candidates",
    ),
    project_id: str | None = typer.Option(None, "--project-id", help="override project id"),
    source: list[str] = typer.Option([], "--source", help="repeatable data source hint (reddit/github/search/...)"),
    plan: bool = typer.Option(False, "--plan", help="auto-build factory plan from the top candidate"),
    plan_opp: str | None = typer.Option(None, "--plan-opp", help="opportunity_id to plan (default: top candidate)"),
    plan_out_dir: Path | None = typer.Option(None, "--plan-out-dir", help="plan output dir (default: <out_dir>/plans/<pid>)"),
    backend: str = typer.Option("recipe", "--backend", help="scout backend: recipe | web"),
) -> None:
    """V3: scout a market direction into opportunity candidates (Market Scout)."""
    from .agents.base import AgentInput
    from .agents.scout import MarketScoutAgent, RecipeBackend, WebBackend, _slug

    if backend not in ("recipe", "web"):
        typer.echo(f"unknown backend: {backend} (expected recipe|web)")
        raise typer.Exit(1)

    pid = project_id or _slug(query)
    workdir = out_dir / pid
    workdir.mkdir(parents=True, exist_ok=True)

    agent = MarketScoutAgent(backend=RecipeBackend() if backend == "recipe" else WebBackend())
    out = agent.run(
        AgentInput(
            agent="scout",
            project_id=pid,
            task_id="scout",
            goal=query,
            constraints=source,
            workdir=str(workdir),
        )
    )
    if out.status != "completed":
        typer.echo(f"Scout failed: {out.summary}")
        raise typer.Exit(1)

    typer.echo(f"Candidates  : {workdir / 'opportunities.json'}")
    typer.echo(f"Summary     : {workdir / 'opportunities.md'}")

    if plan:
        _scout_plan(pid, workdir, plan_opp, plan_out_dir or (out_dir / "plans" / pid))


def _scout_plan(pid: str, workdir: Path, plan_opp: str | None, plan_out_dir: Path) -> None:
    """V3->V2 bridge: turn the top (or named) opportunity candidate into a plan."""
    from json import loads

    from .agents.scout import Opportunity

    opp_path = workdir / "opportunities.json"
    candidates = [Opportunity.model_validate(d) for d in loads(opp_path.read_text(encoding="utf-8"))]
    if not candidates:
        typer.echo("No opportunity candidates found; nothing to plan.")
        raise typer.Exit(1)
    opp = next((o for o in candidates if o.opportunity_id == plan_opp), None) if plan_opp else candidates[0]
    if opp is None:
        typer.echo(f"opportunity '{plan_opp}' not found in {opp_path}")
        raise typer.Exit(1)

    goal = f"{opp.hypothesis}"
    constraints = []
    for p in opp.pains:
        constraints.append(f"{p.persona}: {p.problem}")
    typer.echo(f"Planning top candidate: {opp.opportunity_id} (score={opp.score})")
    _plan_pipeline(pid, plan_out_dir, goal, constraints, [])


@app.command()
def validate(
    opps: Path = typer.Argument(..., help="path to opportunities.json from factory scout"),
    out_dir: Path | None = typer.Option(None, "--out-dir", help="output dir for validations (default: same dir as opps)"),
    opp_id: str | None = typer.Option(None, "--opp", help="validate only this opportunity_id"),
    evidence_threshold: float = typer.Option(0.40, "--evidence-threshold", help="minimum evidence score to pass the gate"),
    conversion_threshold: float = typer.Option(0.03, "--conversion-threshold", help="minimum measured conversion to BUILD"),
    conversion: list[str] = typer.Option([], "--conversion", help="repeatable simulated experiment result: opp_id=0.083"),
) -> None:
    """V4: validate scouted opportunities into BUILD / TEST / KILL."""
    from json import loads

    from .agents.base import AgentInput
    from .agents.validation import ValidationEngine

    candidates = [dict(d) for d in loads(opps.read_text(encoding="utf-8"))]
    if opp_id:
        candidates = [c for c in candidates if c["opportunity_id"] == opp_id]
        if not candidates:
            typer.echo(f"opportunity '{opp_id}' not found in {opps}")
            raise typer.Exit(1)

    conversions: dict[str, float] = {}
    for item in conversion:
        if "=" not in item:
            typer.echo(f"invalid --conversion '{item}' (expected opp_id=0.083)")
            raise typer.Exit(1)
        oid, raw = item.split("=", 1)
        conversions[oid] = float(raw)

    workdir = (out_dir or opps.parent)
    workdir.mkdir(parents=True, exist_ok=True)
    # stage opportunities.json next to the validation output so the agent
    # contract (read opportunities.json -> write validations.*) holds
    staged = workdir / "opportunities.json"
    if not staged.exists() or staged.resolve() != opps.resolve():
        staged.write_text(opps.read_text(encoding="utf-8"), encoding="utf-8")

    engine = ValidationEngine(
        evidence_threshold=evidence_threshold,
        conversion_threshold=conversion_threshold,
    )
    out = engine.run(
        AgentInput(
            agent="validation",
            project_id="validation",
            task_id="validate",
            goal="validate scouted opportunities",
            constraints=[],
            workdir=str(workdir),
            context={"conversion_rates": conversions},
        )
    )
    if out.status != "completed":
        typer.echo(f"Validation failed: {out.summary}")
        raise typer.Exit(1)

    typer.echo(f"Decisions    : {workdir / 'validations.json'}")
    typer.echo(f"Summary      : {workdir / 'validations.md'}")
    typer.echo(out.summary)


def _print_report(report: dict, project_id: str) -> None:
    typer.echo("")
    typer.echo(f"project: {project_id}")
    for tid, t in report.get("tasks", {}).items():
        typer.echo(
            f"  {tid:<6} verdict={t.get('verdict','?'):<8} "
            f"attempts={t.get('retries',0)} repairs={t.get('repair_count',0)}"
        )
        for g in t.get("gates", []):
            flag = "ok " if (g["passed"] or g["skipped"]) else "FAIL"
            typer.echo(f"    gate {g['gate']:<12} {flag}")
    typer.echo(f"summary: {report.get('summary', {})}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    app()
