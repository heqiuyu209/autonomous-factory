"""Task Graph model (blueprint §8).

A task graph is a DAG of work items with dependencies, acceptance criteria
and per-task budgets. It is loaded from JSON/YAML, validated, then executed
in topological order by the orchestrator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..safety import ensure_safe_id


class TaskDef(BaseModel):
    id: str  # e.g. "T010"
    title: str
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)  # outputs this task owns
    token_budget: int | None = None
    runtime_budget_s: int | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _safe_id(cls, v: str) -> str:
        return ensure_safe_id(v, field="task id")

    @field_validator("files")
    @classmethod
    def _safe_files(cls, v: list[str]) -> list[str]:
        from ..safety import safe_join

        for f in v:
            # validate without touching the filesystem: join against a
            # throwaway root only to enforce rel / no-escape semantics.
            safe_join(Path("."), f, field="task file")
        return v


class TaskGraph(BaseModel):
    project_id: str
    name: str
    tasks: list[TaskDef]
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def _safe_project_id(cls, v: str) -> str:
        return ensure_safe_id(v, field="project id")

    @field_validator("tasks")
    @classmethod
    def _verify_dag(cls, v: list[TaskDef]) -> list[TaskDef]:
        ids = {t.id for t in v}
        if len(ids) != len(v):
            raise ValueError("task ids must be unique")
        for t in v:
            for dep in t.dependencies:
                if dep not in ids:
                    raise ValueError(
                        f"task {t.id} depends on unknown task {dep}"
                    )
        cls._assert_acyclic(v)
        return v

    @staticmethod
    def _assert_acyclic(tasks: list[TaskDef]) -> None:
        # Kahn's algorithm colouring: detect cycles without mutating
        indeg = {t.id: 0 for t in tasks}
        adj: dict[str, list[str]] = {t.id: [] for t in tasks}
        for t in tasks:
            for dep in t.dependencies:
                adj[dep].append(t.id)
                indeg[t.id] += 1
        from collections import deque

        q = deque([n for n, d in indeg.items() if d == 0])
        seen = 0
        while q:
            n = q.popleft()
            seen += 1
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        if seen != len(tasks):
            raise ValueError("task graph contains a cycle")

    # -------- helpers ---------------------------------------------------
    def by_id(self, task_id: str) -> TaskDef:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)

    def topological_order(self) -> list[str]:
        """Return task ids in a valid topological order."""
        indeg = {t.id: 0 for t in self.tasks}
        adj: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for t in self.tasks:
            for dep in t.dependencies:
                adj[dep].append(t.id)
                indeg[t.id] += 1
        from collections import deque

        q = deque(sorted(n for n, d in indeg.items() if d == 0))
        order: list[str] = []
        while q:
            n = q.popleft()
            order.append(n)
            for m in sorted(adj[n]):
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        return order

    def ready_tasks(self, completed: set[str]) -> list[str]:
        """Tasks whose dependencies are all completed."""
        return sorted(
            t.id
            for t in self.tasks
            if t.id not in completed and set(t.dependencies) <= completed
        )

    @classmethod
    def load(cls, path: str | Path) -> "TaskGraph":
        path = Path(path)
        # utf-8-sig transparently strips a BOM: Windows editors / PowerShell
        # routinely write UTF-8 JSON/YAML with a leading BOM, which would
        # otherwise break json.loads / yaml.safe_load on line 1.
        raw = path.read_text(encoding="utf-8-sig")
        if path.suffix in (".yaml", ".yml"):
            import yaml

            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)
        return cls.model_validate(data)
