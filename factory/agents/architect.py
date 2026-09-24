"""Architect Agent (blueprint V2).

Turns a PRD (product requirements document) into a validated task graph
(DAG), the native input contract of the V1 development pipeline.

V2 flow:

    problem statement -> [PM] -> PRD -> [Architect] -> task graph -> V1 factory

Two backends (same pattern as CoderAgent/PMAgent):
    RecipeBackend  - deterministic task-graph generator (no API key).
                     Reads the PRD written by the PM recipe and emits a
                     standard implement + harden-test DAG.
    OpenAIBackend  - optional real-LLM architect via an OpenAI-compatible
                     API. Enabled only when OPENAI_API_KEY is present.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..schemas.base import AgentOutput
from ..schemas.task_graph import TaskDef, TaskGraph
from .base import AgentInput

GRAPH_FILENAME = "task_graph.json"
PRD_FILENAME = "prd.md"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _slug(goal: str) -> str:
    """Deterministic safe project id derived from a goal string."""
    words = _SLUG_RE.sub("_", goal.strip().lower()).strip("_")
    words = words[:40].rstrip("_")
    return f"p_{words}" if words else "p_product"


def _first_section(prd: str, heading: str) -> str:
    """Extract the body of the first `## <heading>` section (deterministic)."""
    lines = prd.splitlines()
    out: list[str] = []
    active = False
    for line in lines:
        if line.startswith("## "):
            if active:
                break
            if line[3:].strip().lower() == heading.lower():
                active = True
            continue
        if active:
            stripped = line.strip()
            if stripped:
                out.append(stripped)
    return "\n".join(out) if out else heading


class RecipeBackend:
    """Deterministic task-graph generator used for demo/E2E without any API key."""

    name = "recipe"

    def run(self, task: AgentInput) -> AgentOutput:
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        prd_path = workdir / PRD_FILENAME
        prd = prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""
        goal = _first_section(prd, "Goal") if prd else task.goal
        acceptance = _first_section(prd, "Acceptance criteria") if prd else ""

        project_id = (
            task.context.get("project_id") or task.project_id or _slug(task.goal)
        )
        graph = TaskGraph(
            project_id=project_id,
            name=f"Product: {goal[:60]}",
            meta={"prd_path": PRD_FILENAME, "generated_by": "architect-recipe"},
            tasks=[
                TaskDef(
                    id="T001",
                    title="implement product with tests",
                    description=(
                        f"Implement the MVP described in the PRD.\nGoal: {goal}"
                    ),
                    dependencies=[],
                    acceptance=[
                        "sample_app package exists and is importable",
                        "unit tests cover the MVP behaviour",
                        "all unit tests pass",
                    ],
                    files=[
                        "sample_app/__init__.py",
                        "sample_app/calc.py",
                        "tests/test_calc.py",
                    ],
                    meta={"target": "all"},
                ),
                TaskDef(
                    id="T002",
                    title="harden test suite (regression guard)",
                    description=(
                        "Reassert the test suite on top of the merged main; "
                        "acts as an integration gate."
                        + (f"\nAcceptance:\n{acceptance}" if acceptance else "")
                    ),
                    dependencies=["T001"],
                    acceptance=[
                        "tests cover the MVP behaviour end to end",
                        "no regressions on merged main",
                    ],
                    files=["tests/test_calc.py"],
                    meta={"target": "tests"},
                ),
            ],
        )
        dst = workdir / GRAPH_FILENAME
        dst.write_text(
            graph.model_dump_json(indent=2), encoding="utf-8"
        )
        return AgentOutput(
            status="completed",
            summary=f"wrote task graph {project_id} with {len(graph.tasks)} tasks",
            artifacts=[GRAPH_FILENAME],
        )


class OpenAIBackend:
    """Optional real-LLM architect (OpenAI-compatible).

    Requires OPENAI_API_KEY; otherwise ArchitectAgent uses RecipeBackend.
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
            "You are a software architect. Read the PRD and emit a task graph "
            "as JSON conforming to this schema: "
            '{"project_id": str, "name": str, "tasks": [{"id": str, '
            '"title": str, "description": str, "dependencies": [str], '
            '"acceptance": [str], "files": [str], "meta": {}}]}. '
            "The graph MUST be a DAG. Output ONLY the JSON object."
        )
        workdir = Path(task.workdir)
        prd_path = workdir / PRD_FILENAME
        prd = prd_path.read_text(encoding="utf-8") if prd_path.exists() else task.goal
        user = f"PRD:\n{prd}\n\nProject id hint: {task.context.get('project_id') or ''}"
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
            # A model-layer failure is a *failed attempt*, shaped as failed
            # AgentOutput so callers can route it through normal error paths.
            return AgentOutput(status="failed", summary=f"LLM backend error: {exc!r}")
        if not content:
            return AgentOutput(status="failed", summary="LLM returned empty task graph")
        try:
            start = content.find("{")
            end = content.rfind("}")
            graph = TaskGraph.model_validate(json.loads(content[start : end + 1]))
        except Exception as exc:
            # Invalid / cyclic / unknown-dependency graphs are rejected here:
            # never hand the orchestrator an unvalidated DAG.
            return AgentOutput(
                status="failed",
                summary=f"LLM returned invalid task graph: {exc!r}",
            )
        dst = workdir / GRAPH_FILENAME
        dst.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
        return AgentOutput(
            status="completed",
            summary=f"LLM wrote task graph {graph.project_id} with {len(graph.tasks)} tasks",
            artifacts=[GRAPH_FILENAME],
        )


class ArchitectAgent:
    def __init__(self, backend=None):
        self.backend = backend or self._auto_backend()

    @staticmethod
    def _auto_backend():
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIBackend()
        return RecipeBackend()

    def run(self, task: AgentInput) -> AgentOutput:
        return self.backend.run(task)
