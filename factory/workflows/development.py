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
from ..models import Project
from ..orchestrator import FactoryOrchestrator
from ..schemas.task_graph import TaskGraph
from ..state_machine import ProjectState  # noqa: F401  (state vocabulary)


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
        seed_bug: bool = True,
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
