"""Safety-guard tests: identifier validation, path traversal protection and
schema-level rejection - the trust boundary for untrusted graph/LLM input."""
from __future__ import annotations

import pytest

from factory.safety import ensure_safe_id, safe_join
from factory.schemas.task_graph import TaskDef, TaskGraph


# --------------------------------------------------------------------------
# ensure_safe_id
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["T001", "p_demo_calc", "a1", "x-y_z", "A0"],
)
def test_safe_id_accepted(value):
    assert ensure_safe_id(value) == value


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "../x", "a/b", "a\\b", "a b", "-start", "_start", "x.y", "a:b", "..\\x"],
)
def test_safe_id_rejected(value):
    with pytest.raises(ValueError):
        ensure_safe_id(value)


# --------------------------------------------------------------------------
# safe_join
# --------------------------------------------------------------------------
def test_safe_join_nested_ok(tmp_path):
    p = safe_join(tmp_path, "src/app/main.py")
    assert p == (tmp_path / "src" / "app" / "main.py").resolve()


@pytest.mark.parametrize(
    "rel",
    ["../escape.py", "a/../../escape.py", "/abs/file.py", "C:\\win\\file.py", ""],
)
def test_safe_join_rejects_escape(tmp_path, rel):
    with pytest.raises(ValueError):
        safe_join(tmp_path, rel)


# --------------------------------------------------------------------------
# schema-level rejection (TaskGraph / TaskDef)
# --------------------------------------------------------------------------
def test_taskdef_rejects_unsafe_id():
    with pytest.raises(ValueError):
        TaskDef(id="../evil", title="t")


def test_taskdef_rejects_unsafe_files():
    with pytest.raises(ValueError):
        TaskDef(id="T001", title="t", files=["ok.py", "../../etc/evil.py"])


def test_taskgraph_rejects_unsafe_project_id():
    with pytest.raises(ValueError):
        TaskGraph(project_id="../../..", name="n", tasks=[])
