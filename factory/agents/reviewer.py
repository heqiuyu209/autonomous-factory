"""Reviewer Agent (blueprint §10, §20).

The reviewer is intentionally isolated from the coder: it receives only
the task specification, the produced file set and the code - never the
coder's reasoning. If the reviewer says "the code is good", that claim is
backed by explicit issues/evidence, and the machine verifier still has
the final say.

V1 ships a deterministic RuleReviewer (works offline); an LLM reviewer
can be dropped in by implementing the same ReviewBackend protocol.
"""
from __future__ import annotations

from pathlib import Path

from ..safety import safe_join
from ..schemas.base import Evidence
from .base import AgentInput

REVIEW_TEMPLATE = """\
Review target       : {task_id} ({title})
Reviewed files      : {files}
Acceptance criteria : {acceptance}
"""


class RuleReviewBackend:
    """Deterministic reviewer: checks concrete properties, no LLM needed.

    Checks (each maps to evidence):
      1. declared output files exist in the worktree
      2. no unresolved placeholder markers (BUG/TODO/FIXME)
      3. tests directory present
    """

    name = "rule"

    def review(self, task: AgentInput, produced: list[str]) -> dict:
        issues: list[dict] = []
        checks: list[Evidence] = []
        workdir = Path(task.workdir)

        # 1. declared files exist (schema-validated; guarded here defensively)
        missing: list[str] = []
        for f in task.context.get("expected_files", []):
            try:
                p = safe_join(workdir, f)
            except ValueError:
                missing.append(f)  # unsafe path counts as not produced
                continue
            if not p.exists():
                missing.append(f)
        if missing:
            issues.append(
                {
                    "severity": "critical",
                    "file": ",".join(missing),
                    "reason": f"declared output files not produced: {missing}",
                }
            )
        checks.append(
            Evidence(
                kind="file_existence",
                detail=f"missing={missing}",
                value=0.0 if missing else 1.0,
            )
        )

        # 2. placeholder / bug markers
        markers = ("BUG", "TODO", "FIXME", "XXX", "HACK", "IMPLEMENT ME")
        hits: list[str] = []
        for p in workdir.rglob("*.py"):
            if ".venv" in p.parts:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for m in markers:
                if m in text:
                    hits.append(f"{p.name}:{m}")
        if hits:
            issues.append(
                {
                    "severity": "warning",
                    "file": "-",
                    "reason": f"marker tokens found: {hits[:10]}",
                }
            )
        checks.append(Evidence(kind="marker_scan", detail=str(hits), value=0.0 if hits else 1.0))

        # 3. tests present
        test_files = list(workdir.rglob("test_*.py"))
        checks.append(
            Evidence(
                kind="tests_present",
                detail=f"{len(test_files)} test files",
                value=1.0 if test_files else 0.0,
            )
        )
        if not test_files:
            issues.append(
                {"severity": "warning", "file": "-", "reason": "no test files found"}
            )

        # 4. final verdict: only critical findings block; warnings are
        #    documented but not blocking (the machine verifier has final say).
        verdict = (
            "APPROVE"
            if not any(i["severity"] == "critical" for i in issues)
            else "REJECT"
        )
        confidence = max(0.0, 1.0 - sum(i["severity"] == "critical" for i in issues) * 0.5)
        return {
            "verdict": verdict,
            "issues": issues,
            "checks": [c.model_dump() for c in checks],
            "confidence": confidence,
        }


class ReviewerAgent:
    def __init__(self, backend=None):
        self.backend = backend or RuleReviewBackend()

    def run(self, task: AgentInput, produced: list[str]) -> dict:
        result = self.backend.review(task, produced)
        result["reviewed_files"] = produced
        return result
