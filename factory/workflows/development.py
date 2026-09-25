"""Development workflow - the 'SOFTWARE FACTORY' pumping station.

Wraps the orchestrator as a durable, resumable pipeline:

    PRD -> Task Graph -> Coder/Verifier/Reviewer -> Merged main

V1 implements exactly the core the blueprint says to build first:
the thing that turns "a goal" into "a verified application".
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..db import init_db, session_scope
from ..models import Project, RunRecord
from ..orchestrator import FactoryOrchestrator
from ..schemas.task_graph import TaskGraph
from ..state_machine import (
    ProjectState,
    StateMachineError,
    TaskState,
)


class DevelopmentWorkflow:
    def __init__(
        self,
        orchestrator: FactoryOrchestrator | None = None,
        workspace_root: Path | None = None,
    ):
        self.workspace_root = workspace_root or settings.workspace_root
        self.orchestrator = orchestrator or FactoryOrchestrator(
            workspace_root=self.workspace_root
        )

    def plan(
        self,
        project_id: str,
        name: str,
        prd_path: str | None = None,
        task_graph_path: str | None = None,
    ) -> Project:
        """Register (or load) a project record. Durable before any coding."""
        init_db()
        with session_scope() as session:
            proj = session.get(Project, project_id)
            if proj is None:
                proj = Project(
                    id=project_id,
                    name=name,
                    state="PLANNING",
                    prd_path=prd_path,
                    task_graph_path=task_graph_path,
                )
                session.add(proj)
                session.flush()
            return proj

    def build(
        self,
        project_id: str,
        graph: TaskGraph,
        *,
        seed_bug: bool = False,
    ) -> dict:
        """Execute the graph; durable and resumable across crashes."""
        return self.orchestrator.run_graph(
            project_id=project_id,
            name=graph.name,
            graph=graph,
            prd_path=graph.meta.get("prd_path"),
            seed_bug=seed_bug,
        )

    def run(self, prd_path: str, graph_path: str) -> dict:
        graph = TaskGraph.load(graph_path)
        self.plan(graph.project_id, graph.name, prd_path, graph_path)
        return self.build(graph.project_id, graph)

    @staticmethod
    def status(project_id: str) -> dict:
        with session_scope() as session:
            proj = session.get(Project, project_id)
            if proj is None:
                return {"exists": False}
            tasks = [
                {
                    "task": t.task_id,
                    "state": t.state,
                    "retries": t.retries,
                    "detail": t.detail,
                }
                for t in proj.tasks
            ]
            reviews = [
                {"task": r.task_id, "verdict": r.verdict}
                for r in proj.reviews
            ]
            return {
                "exists": True,
                "project_id": proj.id,
                "state": proj.state,
                "tasks": tasks,
                "reviews": reviews,
            }

    def promote(self, project_id: str) -> dict:
        """Milestone promotion (blueprint §22 lifecycle).

        Walk a fully-built project through the remaining state-machine stages
        to PRODUCTION. Eligibility is proven from the DB (the durable source
        of truth), never assumed:

          * the project exists and is at REVIEWING (or already mid-promotion);
          * every task is DONE - no task BLOCKED;
          * every recorded review for the project is APPROVE.

        Each hop is a legal state-machine transition audited as a
        ``RunRecord(kind="PROMOTE")``; an ineligible project is left
        untouched (no state mutation on failure).
        """
        init_db()
        chain = (
            ProjectState.TESTING,
            ProjectState.SECURITY_REVIEW,
            ProjectState.PERF_TEST,
            ProjectState.STAGING,
            ProjectState.CANARY,
            ProjectState.PRODUCTION,
        )
        with session_scope() as session:
            proj = session.get(Project, project_id)
            if proj is None:
                return {"exists": False}
            start = ProjectState(proj.state)
            if start is ProjectState.PRODUCTION:
                return {
                    "exists": True,
                    "project_id": proj.id,
                    "state": "PRODUCTION",
                    "already_production": True,
                }
            tasks = proj.tasks
            if not tasks:
                raise StateMachineError(
                    "promote requires a planned task graph"
                )
            not_done = [
                t.task_id for t in tasks if t.state != TaskState.DONE.value
            ]
            if not_done:
                raise StateMachineError(
                    f"cannot promote: tasks not DONE: {not_done} "
                    "(all tasks must be DONE before promotion)"
                )
            rejected = [
                r.task_id for r in proj.reviews if r.verdict != "APPROVE"
            ]
            if rejected:
                raise StateMachineError(
                    f"cannot promote: reviews not APPROVE for task ids: "
                    f"{rejected}"
                )
            # resume-safe: a project already mid-promotion keeps its stage and
            # advances from the *next* hop instead of re-applying its own.
            cur = start
            idx = chain.index(cur) + 1 if cur in chain else 0
            advanced: list[str] = []
            for stage in chain[idx:]:
                nxt = self.orchestrator.machine.transition(
                    cur, stage, project=True
                )
                proj.state = nxt.value
                session.add(
                    RunRecord(
                        project_id=proj.id,
                        kind="PROMOTE",
                        status="ok",
                        detail={"stage": nxt.value},
                    )
                )
                advanced.append(nxt.value)
                cur = nxt
            session.flush()
            return {
                "exists": True,
                "project_id": proj.id,
                "state": proj.state,
                "advanced": advanced,
            }
