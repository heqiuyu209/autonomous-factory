"""Durable state machine (blueprint §22).

The factory's brain is a state machine, not a while-loop. Every transition
must be sanctioned by a policy + evidence + gate check so that a machine
restart, model failure or agent crash never loses project state.

States track both PROJECT lifecycle and per-TASK lifecycle.
"""
from __future__ import annotations

from enum import Enum


class ProjectState(str, Enum):
    DISCOVERING = "DISCOVERING"
    ANALYZING = "ANALYZING"
    VALIDATING = "VALIDATING"
    PLANNING = "PLANNING"
    BUILDING = "BUILDING"
    REVIEWING = "REVIEWING"
    TESTING = "TESTING"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    PERF_TEST = "PERF_TEST"
    STAGING = "STAGING"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"
    MEASURING = "MEASURING"
    ITERATING = "ITERATING"
    KILLED = "KILLED"


class TaskState(str, Enum):
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_VERIFY = "WAITING_VERIFY"
    VERIFY_FAILED = "VERIFY_FAILED"
    WAITING_REVIEW = "WAITING_REVIEW"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


# --------------------------------------------------------------------------
# Transition tables
# --------------------------------------------------------------------------
_PROJECT_TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.DISCOVERING: {ProjectState.ANALYZING, ProjectState.KILLED},
    ProjectState.ANALYZING: {ProjectState.VALIDATING, ProjectState.KILLED},
    ProjectState.VALIDATING: {ProjectState.PLANNING, ProjectState.KILLED},
    ProjectState.PLANNING: {ProjectState.BUILDING, ProjectState.KILLED},
    ProjectState.BUILDING: {ProjectState.REVIEWING, ProjectState.KILLED},
    ProjectState.REVIEWING: {ProjectState.TESTING, ProjectState.KILLED},
    ProjectState.TESTING: {ProjectState.SECURITY_REVIEW, ProjectState.KILLED},
    ProjectState.SECURITY_REVIEW: {ProjectState.PERF_TEST, ProjectState.KILLED},
    ProjectState.PERF_TEST: {ProjectState.STAGING, ProjectState.KILLED},
    ProjectState.STAGING: {ProjectState.CANARY, ProjectState.KILLED},
    ProjectState.CANARY: {ProjectState.PRODUCTION, ProjectState.ITERATING},
    ProjectState.PRODUCTION: {ProjectState.MEASURING},
    ProjectState.MEASURING: {ProjectState.ITERATING, ProjectState.KILLED},
    ProjectState.ITERATING: {
        ProjectState.ANALYZING,
        ProjectState.VALIDATING,
        ProjectState.PLANNING,
        ProjectState.BUILDING,
        ProjectState.MEASURING,
        ProjectState.KILLED,
    },
    ProjectState.KILLED: set(),
}

_TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.READY: {TaskState.IN_PROGRESS, TaskState.BLOCKED},
    TaskState.IN_PROGRESS: {
        TaskState.WAITING_VERIFY,
        TaskState.BLOCKED,
        TaskState.READY,  # retried
    },
    TaskState.WAITING_VERIFY: {
        TaskState.WAITING_REVIEW,
        TaskState.VERIFY_FAILED,
        TaskState.BLOCKED,
        TaskState.READY,  # crash recovery / re-queue
    },
    TaskState.VERIFY_FAILED: {
        TaskState.IN_PROGRESS,  # coder repair
        TaskState.BLOCKED,
        TaskState.READY,  # crash recovery / re-queue
    },
    TaskState.WAITING_REVIEW: {
        TaskState.DONE,
        TaskState.REVIEW_REJECTED,
        TaskState.BLOCKED,
        TaskState.READY,  # crash recovery / re-queue
    },
    TaskState.REVIEW_REJECTED: {
        TaskState.IN_PROGRESS,  # coder repair
        TaskState.BLOCKED,
        TaskState.READY,  # crash recovery / re-queue
    },
    TaskState.BLOCKED: {TaskState.IN_PROGRESS, TaskState.READY},
    TaskState.DONE: set(),
}

_PROJECT_TERMINAL = {ProjectState.KILLED}
_TASK_TERMINAL = {TaskState.DONE, TaskState.BLOCKED}


class StateMachineError(Exception):
    """Raised on an illegal or ungated transition."""


class TransitionGate:
    """User-provided hook: return True to allow the transition.

    The gate decouples *transition legality* (this module) from
    *policy/evidence* (policy.py), keeping the machine deterministic.
    """

    def allow(self, _state, _next_state, _context) -> bool:
        return True


class StateMachine:
    def __init__(self, gate: TransitionGate | None = None):
        self._gate = gate or TransitionGate()

    def can_transition(self, state, next_state, *, project: bool = True) -> bool:
        table = _PROJECT_TRANSITIONS if project else _TASK_TRANSITIONS
        return next_state in table.get(state, set())

    def is_terminal(self, state, *, project: bool = True) -> bool:
        return (
            state in _PROJECT_TERMINAL
            if project
            else state in _TASK_TERMINAL
        )

    def transition(self, state, next_state, *, project: bool = True, context=None):
        """Validate legality + gate, then return next_state."""
        if not self.can_transition(
            state, next_state, project=project
        ):
            raise StateMachineError(
                f"illegal transition {state} -> {next_state} "
                f"({'project' if project else 'task'})"
            )
        if not self._gate.allow(state, next_state, context or {}):
            raise StateMachineError(
                f"transition {state} -> {next_state} blocked by policy gate"
            )
        return next_state


# singleton for default use
default_machine = StateMachine()
