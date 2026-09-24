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
    from .agents.architect import ArchitectAgent, _slug
    from .agents.base import AgentInput
    from .agents.pm import PMAgent

    pid = project_id or _slug(goal)
    workdir = out_dir / pid
    workdir.mkdir(parents=True, exist_ok=True)

    pm_out = PMAgent().run(
        AgentInput(
            agent="pm",
            project_id=pid,
            task_id="plan",
            goal=goal,
            constraints=constraint,
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
