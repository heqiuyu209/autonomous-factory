"""State machine tests."""
from __future__ import annotations

import pytest

from factory.state_machine import (
    ProjectState,
    StateMachine,
    StateMachineError,
    TaskState,
    TransitionGate,
)


def test_project_legal_transition():
    m = StateMachine()
    assert m.can_transition(ProjectState.PLANNING, ProjectState.BUILDING, project=True)
    assert m.transition(ProjectState.PLANNING, ProjectState.BUILDING, project=True) == ProjectState.BUILDING


def test_project_illegal_transition():
    m = StateMachine()
    assert not m.can_transition(ProjectState.PLANNING, ProjectState.PRODUCTION, project=True)
    with pytest.raises(StateMachineError):
        m.transition(ProjectState.PLANNING, ProjectState.PRODUCTION, project=True)


def test_task_pipeline_flow():
    m = StateMachine()
    s = TaskState.READY
    s = m.transition(s, TaskState.IN_PROGRESS, project=False)
    s = m.transition(s, TaskState.WAITING_VERIFY, project=False)
    s = m.transition(s, TaskState.WAITING_REVIEW, project=False)
    s = m.transition(s, TaskState.DONE, project=False)
    assert m.is_terminal(TaskState.DONE, project=False)


def test_task_repair_flow():
    m = StateMachine()
    s = m.transition(TaskState.WAITING_VERIFY, TaskState.VERIFY_FAILED, project=False)
    s = m.transition(s, TaskState.IN_PROGRESS, project=False)
    assert s == TaskState.IN_PROGRESS


def test_gate_can_block():
    class DenyGate(TransitionGate):
        def allow(self, state, next_state, context=None) -> bool:
            return False

    m = StateMachine(gate=DenyGate())
    with pytest.raises(StateMachineError, match="blocked by policy gate"):
        m.transition(TaskState.READY, TaskState.IN_PROGRESS, project=False)


def test_terminal_states_are_terminal():
    m = StateMachine()
    assert m.is_terminal(ProjectState.KILLED, project=True)
    assert not m.is_terminal(ProjectState.BUILDING, project=True)
