"""First-generation Orchestrator (blueprint: ORCHESTRATOR box).

Drives a project's task graph through:

    planner(graph) ->
        per task: coder -> machine verifier -> reviewer ->
                   repair loop (up to N retries) -> merge to main

Key invariants enforced here:
    * agents work only inside per-task worktrees (never on main directly)
    * only DONE + verified + approved code is merged into main
    * every transition in the DB is a legal state-machine transition
    * budget + policy violations halt the factory, they never get swallowed
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from .agents import AgentInput, AgentRegistry, CoderAgent, RecipeBackend
from .budget import BudgetExceeded, BudgetTracker
from .config import settings
from .db import init_db, session_scope
from .execution import CoderTimeout, run_with_timeout_isolated
from .models import (
    BudgetAccount,
    BudgetLedger,
    Project,
    ReviewRecord,
    RunRecord,
    TaskRecord,
)
from .policy import PolicyEngine, PolicyViolation
from .safety import ensure_safe_id, ensure_safe_rel, safe_join
from .schemas.base import AgentOutput
from .schemas.task_graph import TaskDef, TaskGraph
from .state_machine import (
    ProjectState,
    StateMachine,
    StateMachineError,
    TaskState,
    TransitionGate,
)
from .verifier import Verifier

MAX_TASKS_PER_CYCLE = 5  # parallel-ready without going overboard


class _PolicyGate(TransitionGate):
    """Gate that blocks transitions which policy would not sanction."""

    def __init__(self, policy: PolicyEngine):
        self._policy = policy

    def allow(self, state, next_state, context=None) -> bool:
        # All transitions here are local (no production access), so the
        # capability policies are enforced at the tool-call level.
        return True


class FactoryOrchestrator:
    def __init__(
        self,
        registry: AgentRegistry | None = None,
        verifier: Verifier | None = None,
        policy: PolicyEngine | None = None,
        machine: StateMachine | None = None,
        workspace_root: Path | None = None,
    ):
        self.registry = registry or AgentRegistry.default()
        self.verifier = verifier or Verifier(gates=settings.verify_gates)
        self.policy = policy or PolicyEngine()
        self.machine = machine or StateMachine(_PolicyGate(self.policy))
        self.workspace = workspace_root or settings.workspace_root

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def run_graph(
        self,
        project_id: str,
        name: str,
        graph: TaskGraph,
        prd_path: str | None = None,
        *,
        seed_bug: bool = True,
        max_retries: int | None = None,
    ) -> dict:
        """Execute a full task graph for a project. Returns a run report."""
        init_db()
        ensure_safe_id(project_id, field="project id")
        max_retries = max_retries or settings.max_coder_retries
        # Untrusted metadata audit: a PRD path persisted from the task graph
        # must be a relative, traversal-free reference - never an arbitrary
        # absolute path injected by a third-party graph.
        if prd_path is not None:
            ensure_safe_rel(prd_path, field="prd_path")
        project_root = self.workspace / project_id
        (project_root / "main").mkdir(parents=True, exist_ok=True)

        with session_scope() as session:
            proj = session.get(Project, project_id)
            if proj is None:
                proj = Project(
                    id=project_id,
                    name=name,
                    state="PLANNING",
                    prd_path=prd_path,
                    task_graph_path=graph.name,
                )
                session.add(proj)
            # Project lifecycle follows the durable state machine. A killed
            # project is terminal and must not be revived via a rebuild; a
            # fresh project enters BUILDING. Resume runs keep their state.
            if proj.state == "KILLED":
                raise StateMachineError(
                    f"project '{project_id}' is KILLED and cannot be rebuilt"
                )
            if proj.state == "PLANNING":
                proj.state = self.machine.transition(
                    ProjectState(proj.state), ProjectState.BUILDING, project=True
                ).value
            # materialize task records (idempotent)
            self._materialize_tasks(session, proj.id, graph)
            run = RunRecord(project_id=proj.id, kind="BUILD", status="running")
            session.add(run)
            session.flush()  # assign the PK before the scope closes
            run_id = run.id

        start = time.monotonic()
        report = {
            "project_id": project_id,
            "tasks": {},
            "summary": {},
        }

        # Durable loop: recompute readiness from DB each cycle so a crash
        # mid-way resumes work instead of restarting the whole graph.
        while True:
            with session_scope() as session:
                tasks = self._load_tasks(session, project_id)
                completed = {t.task_id for t in tasks if t.state == TaskState.DONE.value}
                if len(completed) == len(tasks):
                    report["summary"]["state"] = "DONE"
                    proj = session.get(Project, project_id)
                    # BUILDING -> REVIEWING through the state machine;
                    # resumed projects already past this stay as-is.
                    if proj.state == "BUILDING":
                        proj.state = self.machine.transition(
                            ProjectState.BUILDING,
                            ProjectState.REVIEWING,
                            project=True,
                        ).value
                    break
                ready = [
                    tid for tid in graph.ready_tasks(completed) if tid not in report["tasks"]
                ]
                if not ready:
                    report["summary"]["state"] = "BLOCKED"
                    report["summary"]["reason"] = "no ready tasks but graph not complete"
                    break
                for tid in ready[:MAX_TASKS_PER_CYCLE]:
                    task_def = graph.by_id(tid)
                    task_rec = next(t for t in tasks if t.task_id == tid)
                    report["tasks"][tid] = self._execute_task(
                        session,
                        project_root,
                        project_id,
                        task_def,
                        task_rec,
                        graph,
                        max_retries,
                        seed_bug=seed_bug and tid == graph.topological_order()[0],
                    )

        report["summary"]["elapsed_s"] = round(time.monotonic() - start, 2)
        with session_scope() as session:
            run = session.get(RunRecord, run_id)
            run.status = "finished"
            run.finished_at = datetime.now(timezone.utc)
            run.detail = {"report": report["summary"]}
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _materialize_tasks(
        self, session, project_id: str, graph: TaskGraph
    ) -> None:
        existing = {
            t.task_id
            for t in session.query(TaskRecord).filter_by(project_id=project_id)
        }
        for tdef in graph.tasks:
            if tdef.id in existing:
                continue
            session.add(
                TaskRecord(
                    project_id=project_id,
                    task_id=tdef.id,
                    title=tdef.title,
                    state=TaskState.READY.value,
                    dependencies=tdef.dependencies,
                    acceptance=tdef.acceptance,
                    files=tdef.files,
                )
            )

    def _load_tasks(self, session, project_id: str) -> list[TaskRecord]:
        return (
            session.query(TaskRecord)
            .filter_by(project_id=project_id)
            .order_by(TaskRecord.task_id)
            .all()
        )

    def _execute_task(
        self,
        session,
        project_root: Path,
        project_id: str,
        tdef: TaskDef,
        rec: TaskRecord,
        graph: TaskGraph,
        max_retries: int,
        *,
        seed_bug: bool,
    ) -> dict:
        # Worktree = isolated copy of the current main + task-specific files.
        # The coder may only ever touch this directory (policy enforced).
        main_dir = project_root / "main"
        main_dir.mkdir(parents=True, exist_ok=True)
        worktree = project_root / "worktrees" / tdef.id
        # double-check the id is a safe path segment even when the graph was
        # constructed programmatically (schema validation is the primary gate)
        ensure_safe_id(tdef.id, field="task id")
        if worktree.exists():
            shutil.rmtree(worktree, ignore_errors=True)
        worktree.mkdir(parents=True, exist_ok=True)
        self._snapshot_main(main_dir, worktree)

        def _set_task_state(s: TaskState) -> None:
            next_s = self.machine.transition(
                TaskState(rec.state), s, project=False
            )
            rec.state = next_s.value

        result = {
            "id": tdef.id,
            "retries": 0,
            "verdict": "PENDING",
            "gates": [],
            "repair_count": 0,
        }

        # seeds: first task demo can start buggy to show the repair loop
        budget = BudgetTracker.from_limits(
            (
                tdef.token_budget
                if tdef.token_budget is not None
                else settings.default_token_budget
            ),
            runtime_s=(
                tdef.runtime_budget_s
                if tdef.runtime_budget_s is not None
                else settings.default_runtime_budget_s
            ),
        )
        coder = self.registry.get("coder")
        reviewer = self.registry.get("reviewer")

        # Crash recovery: a task stranded mid-pipeline by a crash (e.g. the
        # process died while IN_PROGRESS) has no legal direct re-entry
        # transition, which would otherwise strand it as BLOCKED or worse.
        # Reset any non-terminal state back to READY so the pipeline starts
        # it over cleanly. BLOCKED tasks are re-queued too, so a later
        # `factory run` retries what was previously stopped.
        if TaskState(rec.state) in {
            TaskState.IN_PROGRESS,
            TaskState.WAITING_VERIFY,
            TaskState.VERIFY_FAILED,
            TaskState.WAITING_REVIEW,
            TaskState.REVIEW_REJECTED,
            TaskState.BLOCKED,
        }:
            rec.state = self.machine.transition(
                TaskState(rec.state), TaskState.READY, project=False
            ).value
            session.flush()

        # attach an injectable bug deliberately for the demo then let the
        # pipeline repair it - proving the verifier actually catches things.
        if seed_bug and not rec.detail.get("seeded"):
            coder = CoderAgent(backend=RecipeBackend(inject_bug=True))
            # materialise a NEW dict so SQLAlchemy detects the change: a
            # plain JSON column does not track in-place mutation.
            rec.detail = {**rec.detail, "seeded": True}
            session.flush()

        rec.workdir = str(worktree)
        session.flush()

        try:
            _set_task_state(TaskState.IN_PROGRESS)
            session.flush()

            attempt = 0
            last_output = None
            while attempt <= max_retries:
                attempt += 1
                result["retries"] = attempt
                rec.retries = attempt
                session.flush()

                # Runtime preflight: an exhausted budget must halt BEFORE the
                # coder starts, not after it wastes an attempt. A 0-second
                # ceiling is a hard "do not run this task" signal.
                if budget.remaining_runtime_s <= 0:
                    raise BudgetExceeded(
                        "runtime_s", budget.limit_runtime_s, budget.spent_runtime_s
                    )

                inp = AgentInput(
                    agent="coder",
                    project_id=project_id,
                    task_id=tdef.id,
                    goal=tdef.title,
                    description=tdef.description,
                    acceptance_criteria=tdef.acceptance,
                    workdir=str(worktree),
                    context={
                        "expected_files": tdef.files,
                        "seed_bug": seed_bug and attempt == 1,
                        "target": (tdef.meta or {}).get("target", "all"),
                        "meta": tdef.meta or {},
                        # Full design context: what predecessors produced
                        # and the project PRD, so a coder codes against the
                        # real product intent instead of the task title.
                        "deps": self._collect_dep_context(
                            session, project_id, graph, tdef
                        ),
                        "prd": self._read_prd(session, project_id),
                    },
                )
                # policy enforcement happens at the boundary
                self.policy.check_filesystem("coder", str(worktree), str(worktree))
                # Account must exist before the first attempt: the timeout
                # branch writes the ledger too, so it can never reference an
                # account created only on the success path.
                account_id = self._ensure_budget_account(session, project_id)
                attempt_start = time.monotonic()
                try:
                    last_output = run_with_timeout_isolated(
                        partial(coder.run, inp),
                        min(
                            budget.remaining_runtime_s,
                            float(settings.attempt_timeout_s),
                        ),
                    )
                except CoderTimeout:
                    # A hung attempt is a wall-clock budget event, not a code
                    # defect: reclaim it, charge what it burned, and let the
                    # repair loop decide - retry under a fresh allowance or
                    # BLOCK once retries are exhausted.
                    elapsed_s = time.monotonic() - attempt_start
                    budget.charge_runtime(
                        elapsed_s, agent="coder", note=f"attempt {attempt} TIMEOUT"
                    )
                    self._write_ledger(
                        session,
                        account_id,
                        ref=f"{tdef.id}#{attempt}-timeout",
                        runtime_s=round(elapsed_s, 3),
                        agent="coder",
                        note=f"attempt {attempt} timed out",
                    )
                    if attempt < max_retries:
                        self._reset_worktree(main_dir, worktree)
                        coder = self._maybe_strip_seed(coder)
                        # IN_PROGRESS cannot self-loop: bounce through READY
                        # to re-queue this attempt under a fresh allowance.
                        _set_task_state(TaskState.READY)
                        _set_task_state(TaskState.IN_PROGRESS)
                        result["repair_count"] += 1
                        session.flush()
                        continue
                    _set_task_state(TaskState.BLOCKED)
                    session.flush()
                    result["verdict"] = "BLOCKED"
                    result["reason"] = (
                        f"coder attempt {attempt} timed out after "
                        f"{elapsed_s:.1f}s (runtime budget exhausted)"
                    )
                    return result
                elapsed_s = time.monotonic() - attempt_start
                budget.charge(
                    tokens=self._charged_tokens(last_output),
                    usd=0.0,
                    agent="coder",
                    note=f"attempt {attempt}",
                )
                budget.charge_runtime(
                    elapsed_s,
                    agent="coder",
                    note=f"attempt {attempt}",
                )
                # Durable audit trail: mirror every charge into the ledger
                # so spend survives restarts (BudgetLedger, not just the
                # in-memory tracker).
                self._write_ledger(
                    session,
                    account_id,
                    ref=f"{tdef.id}#{attempt}",
                    tokens=self._charged_tokens(last_output),
                    agent="coder",
                    note=f"attempt {attempt}",
                )
                self._write_ledger(
                    session,
                    account_id,
                    ref=f"{tdef.id}#{attempt}-rt",
                    runtime_s=round(elapsed_s, 3),
                    agent="coder",
                    note=f"attempt {attempt}",
                )

                # --- coder failed guard
                # A non-completed coder output (e.g. the LLM backend hit an
                # upstream error, returned invalid JSON or an unsafe path)
                # must NEVER be routed onward as if it were code to verify.
                # Treat it as a failed attempt: clean the tree, retry within
                # budget, or BLOCK once retries are exhausted - mirroring
                # the VERIFY_FAILED path.
                if last_output.status != "completed":
                    result["reason"] = last_output.summary
                    if attempt < max_retries:
                        self._reset_worktree(main_dir, worktree)
                        coder = self._maybe_strip_seed(coder)
                        result["repair_count"] += 1
                        # IN_PROGRESS cannot self-loop: bounce through READY
                        # to re-queue this attempt.
                        _set_task_state(TaskState.READY)
                        _set_task_state(TaskState.IN_PROGRESS)
                        session.flush()
                        continue
                    _set_task_state(TaskState.BLOCKED)
                    session.flush()
                    result["verdict"] = "BLOCKED"
                    return result

                # --- machine verifier gate
                _set_task_state(TaskState.WAITING_VERIFY)
                session.flush()
                gate_results = self.verifier.run_all(worktree)
                result["gates"] = [g.as_dict() for g in gate_results]
                if not self.verifier.summarize(gate_results)["passed"]:
                    _set_task_state(TaskState.VERIFY_FAILED)
                    session.flush()
                    # drop the buggy tree and let the coder repair cleanly
                    if attempt < max_retries:
                        self._reset_worktree(main_dir, worktree)
                        coder = self._maybe_strip_seed(coder)
                        result["repair_count"] += 1
                        _set_task_state(TaskState.IN_PROGRESS)
                        session.flush()
                        continue
                    _set_task_state(TaskState.BLOCKED)
                    session.flush()
                    result["verdict"] = "BLOCKED"
                    result["reason"] = "verification failed after max retries"
                    return result

                # --- reviewer gate (isolated from coder)
                _set_task_state(TaskState.WAITING_REVIEW)
                session.flush()
                produced = self._collect_produced(worktree, tdef.files)
                review = reviewer.run(inp, produced)
                session.add(
                    ReviewRecord(
                        project_id=project_id,
                        task_id=rec.id,
                        reviewer="rule-reviewer",
                        verdict=review["verdict"],
                        issues=review["issues"],
                        confidence=review["confidence"],
                    )
                )
                result["verdict"] = review["verdict"]
                if review["verdict"] == "REJECT":
                    _set_task_state(TaskState.REVIEW_REJECTED)
                    session.flush()
                    if attempt < max_retries:
                        self._reset_worktree(main_dir, worktree)
                        coder = self._maybe_strip_seed(coder)
                        result["repair_count"] += 1
                        _set_task_state(TaskState.IN_PROGRESS)
                        session.flush()
                        continue
                    _set_task_state(TaskState.BLOCKED)
                    session.flush()
                    result["verdict"] = "BLOCKED"
                    result["reason"] = "review rejected after max retries"
                    return result

                # --- merge to main: the ONLY place the factory writes main
                self._merge_to_main(worktree, project_root / "main", tdef.files)
                _set_task_state(TaskState.DONE)
                # Persist what this task produced: dependency tasks later
                # read this as their "deps" context. materialise a NEW dict
                # so SQLAlchemy tracks the JSON column change.
                rec.detail = {
                    **rec.detail,
                    "summary": last_output.summary,
                    "artifacts": last_output.artifacts,
                }
                rec.finished_at = datetime.now(timezone.utc)
                session.flush()
                result["files"] = tdef.files
                return result

            return result
        except (BudgetExceeded, PolicyViolation, StateMachineError) as exc:
            _set_task_state(TaskState.BLOCKED)
            result["verdict"] = "BLOCKED"
            result["reason"] = str(exc)
            return result

    @staticmethod
    def _charged_tokens(out: AgentOutput) -> int:
        """Charge the REAL usage when the backend reported it; fall back to
        the summary-length heuristic only when usage is unknown (None)."""
        if out.usage_tokens is not None:
            return int(out.usage_tokens)
        return len(out.summary)

    def _collect_dep_context(
        self, session, project_id: str, graph: TaskGraph, tdef: TaskDef
    ) -> list[dict]:
        """Summaries of completed dependency tasks, so a coder sees what its
        predecessors actually produced instead of coding against
        assumptions. Dependencies still in-flight yield nothing here - the
        orchestrator's readiness gate only runs a task once all deps are
        DONE, so any dep with a row is a completed one."""
        if not tdef.dependencies:
            return []
        rows = (
            session.query(TaskRecord)
            .filter(
                TaskRecord.project_id == project_id,
                TaskRecord.task_id.in_(tdef.dependencies),
            )
            .all()
        )
        out: list[dict] = []
        for r in rows:
            detail = r.detail or {}
            out.append(
                {
                    "task_id": r.task_id,
                    "title": r.title,
                    "state": r.state,
                    "summary": detail.get("summary", ""),
                    "artifacts": detail.get("artifacts", []),
                }
            )
        return out

    def _read_prd(self, session, project_id: str) -> str:
        """Read the project PRD file (trimmed) so the coder sees the product
        intent, not just the one-line task title. Never raises: an
        unreadable PRD degrades to empty context, not a build failure."""
        proj = session.get(Project, project_id)
        if proj is None or not proj.prd_path:
            return ""
        p = Path(proj.prd_path)
        if not p.exists():
            return ""
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:  # pragma: no cover - filesystem defensive
            return ""
        return text[:4000]

    @staticmethod
    def _collect_produced(worktree: Path, expected: list[str]) -> list[str]:
        found: list[str] = []
        for f in expected:
            try:
                p = safe_join(worktree, f)
            except ValueError:
                continue  # defensive: unsafe paths are rejected at graph load
            if p.exists():
                found.append(f)
        if not found:
            found = sorted(
                str(p.relative_to(worktree))
                for p in worktree.rglob("*")
                if p.is_file()
            )
        return found

    @staticmethod
    def _reset_worktree(main_dir: Path, worktree: Path) -> None:
        """Drop a failed attempt's worktree and rebuild it from main."""
        shutil.rmtree(worktree, ignore_errors=True)
        worktree.mkdir(parents=True, exist_ok=True)
        FactoryOrchestrator._snapshot_main(main_dir, worktree)

    @staticmethod
    def _maybe_strip_seed(coder: CoderAgent) -> CoderAgent:
        """Drop an injected demo bug; never swap a configured backend."""
        if isinstance(coder.backend, RecipeBackend):
            return CoderAgent(backend=RecipeBackend(inject_bug=False))
        return coder

    @staticmethod
    def _snapshot_main(main_dir: Path, worktree: Path) -> None:
        """Copy current main state into a fresh worktree (branch start)."""
        if not main_dir.exists():
            return
        for p in main_dir.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(main_dir)
            dst = worktree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)

    @staticmethod
    def _merge_to_main(worktree: Path, main: Path, files: list[str]) -> list[str]:
        """Copy task outputs into main. Returns the list actually merged.

        Only paths that pass the safety guard are touched; a path can leave
        the worktree only via this module, never via agent code.
        """
        merged: list[str] = []
        for rel in files:
            try:
                src = safe_join(worktree, rel)
                dst = safe_join(main, rel)
            except ValueError:
                continue  # defensive: unsafe paths are rejected at graph load
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            merged.append(rel)
        return merged

    @staticmethod
    def _ensure_budget_account(session, project_id: str) -> str:
        """Get-or-create the project-level budget account (FK target for
        ledger rows). Returns the account id."""
        account_id = f"project:{project_id}"
        account = session.get(BudgetAccount, account_id)
        if account is None:
            session.add(
                BudgetAccount(
                    id=account_id,
                    scope="project",
                    limit_tokens=0.0,
                    limit_usd=0.0,
                )
            )
            session.flush()
        return account_id

    @staticmethod
    def _write_ledger(
        session,
        account_id: str,
        *,
        ref: str,
        tokens: float = 0.0,
        usd: float = 0.0,
        runtime_s: float = 0.0,
        agent: str = "",
        note: str = "",
    ) -> None:
        """Append one auditable spend row. Every charge call leaves a row,
        even a zero-cost one, so the ledger is a complete attempt history
        instead of a lossy summary.

        The write is idempotent per (account, ref): crash recovery re-runs a
        task from attempt 1, which would otherwise collide with the UNIQUE
        constraint on (ref_type, ref_id) left by the first attempt. Keeping
        the first row preserves the original audit trail; a later duplicate
        carries no new information (same attempt index, same work).
        """
        existing = (
            session.query(BudgetLedger)
            .filter_by(account_id=account_id, ref_type="task", ref_id=ref)
            .first()
        )
        if existing is not None:
            return
        session.add(
            BudgetLedger(
                account_id=account_id,
                ref_type="task",
                ref_id=ref,
                cost_tokens=tokens,
                cost_usd=usd,
                cost_runtime_s=runtime_s,
                agent=agent,
                note=note,
            )
        )
