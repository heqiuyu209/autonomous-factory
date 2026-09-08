"""Task Graph tests: DAG validation, topo order, readiness."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.schemas.task_graph import TaskGraph


def _graph(tasks: list[dict]) -> TaskGraph:
    return TaskGraph.model_validate({"project_id": "p1", "name": "g", "tasks": tasks})


def test_topological_order_respects_dependencies():
    g = _graph(
        [
            {"id": "T001", "title": "a"},
            {"id": "T002", "title": "b", "dependencies": ["T001"]},
            {"id": "T003", "title": "c", "dependencies": ["T001", "T002"]},
        ]
    )
    order = g.topological_order()
    assert order.index("T001") < order.index("T002") < order.index("T003")


def test_cycle_detected():
    with pytest.raises(ValidationError, match="cycle"):
        _graph(
            [
                {"id": "T001", "title": "a", "dependencies": ["T003"]},
                {"id": "T002", "title": "b", "dependencies": ["T001"]},
                {"id": "T003", "title": "c", "dependencies": ["T002"]},
            ]
        )


def test_unknown_dependency_detected():
    with pytest.raises(ValidationError, match="unknown task"):
        _graph([{"id": "T001", "title": "a"}, {"id": "T002", "title": "b", "dependencies": ["T999"]}])


def test_ready_tasks():
    g = _graph(
        [
            {"id": "T001", "title": "a"},
            {"id": "T002", "title": "b", "dependencies": ["T001"]},
            {"id": "T003", "title": "c", "dependencies": ["T001"]},
        ]
    )
    assert g.ready_tasks(set()) == ["T001"]
    assert g.ready_tasks({"T001"}) == ["T002", "T003"]
    assert g.ready_tasks({"T001", "T002", "T003"}) == []


def test_load_from_json(sample_graph_path):
    g = TaskGraph.load(sample_graph_path)
    assert g.project_id == "p_demo_calc"
    assert {t.id for t in g.tasks} == {"T001", "T002"}
    assert g.by_id("T002").dependencies == ["T001"]
