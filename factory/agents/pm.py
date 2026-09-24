"""PM Agent (blueprint V2).

Turns a problem statement into a PRD (product requirements document).
The PRD is the accepted input contract of the V1 development pipeline
(`factory run --prd prd.md`), so PM is the front-end of the V2 flow:

    problem statement -> [PM] -> PRD -> [Architect] -> task graph -> V1 factory

Two backends (same pattern as CoderAgent):
    RecipeBackend  - deterministic in-process PRD generator (no API key).
                     Used for demos / E2E tests without any external call.
    OpenAIBackend  - optional real-LLM PRD writer via an OpenAI-compatible
                     API. Enabled only when OPENAI_API_KEY is present.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..schemas.base import AgentOutput
from .base import AgentInput

PRD_FILENAME = "prd.md"


def _prd_template(
    goal: str,
    constraints: list[str] | None = None,
    acceptance: list[str] | None = None,
) -> str:
    """Deterministic PRD skeleton aligned with the V1 sample_project format."""
    constraints = constraints or []
    acceptance = acceptance or []
    c_lines = "\n".join(f"- {c}" for c in constraints) or "- 无额外硬约束"
    a_lines = "\n".join(f"- [ ] {a}" for a in acceptance) or "- [ ] 满足 Goal 描述的最小可用实现"
    return f"""# Product

> 由自治软件工厂 PM Agent 生成（RecipeBackend）。

## Goal

{goal}

## Constraints

{c_lines}

## Acceptance criteria

{a_lines}

## Primary metric

- 机器验证门全绿（syntax / test / lint）作为客观门槛

## MVP

- 满足 Goal 的最小可用实现
- 配套单元测试（machine verifier 门槛）
- 可被 V1 流水线独立验证与评审
"""


class RecipeBackend:
    """Deterministic PRD generator used for demo/E2E without any API key."""

    name = "recipe"

    def run(self, task: AgentInput) -> AgentOutput:
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        content = _prd_template(
            task.goal,
            constraints=task.constraints,
            acceptance=task.acceptance_criteria,
        )
        dst = workdir / PRD_FILENAME
        dst.write_text(content, encoding="utf-8")
        return AgentOutput(
            status="completed",
            summary=f"wrote PRD for goal: {task.goal[:80]}",
            artifacts=[PRD_FILENAME],
            evidence=[],
        )


class OpenAIBackend:
    """Optional real-LLM PRD writer (OpenAI-compatible).

    Requires OPENAI_API_KEY; otherwise PMAgent uses RecipeBackend.
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
            "You are a product manager. Write a concise PRD in Markdown "
            "with sections: Goal, Constraints, Acceptance criteria, "
            "Primary metric, MVP. Output ONLY the Markdown body."
        )
        user = (
            f"Problem statement: {task.goal}\n"
            f"Constraints: {task.constraints or 'none'}\n"
            f"Acceptance criteria: {task.acceptance_criteria or 'to be derived'}"
        )
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
            return AgentOutput(status="failed", summary="LLM returned empty PRD")
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        dst = workdir / PRD_FILENAME
        dst.write_text(content, encoding="utf-8")
        return AgentOutput(
            status="completed",
            summary=f"LLM wrote PRD ({len(content)} chars)",
            artifacts=[PRD_FILENAME],
        )


class PMAgent:
    def __init__(self, backend=None):
        self.backend = backend or self._auto_backend()

    @staticmethod
    def _auto_backend():
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIBackend()
        return RecipeBackend()

    def run(self, task: AgentInput) -> AgentOutput:
        return self.backend.run(task)
