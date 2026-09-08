"""Test isolation: each test session gets its own scratch DB + workspace."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from factory.db import configure_database


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.db"
    configure_database(f"sqlite:///{db_path}")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # route orchestrator default workspace into the scratch dir too
    monkeypatch.setenv("FACTORY_WORKSPACE", str(workspace))
    yield workspace
    # ensure engine doesn't hold the file open between tests
    from factory.db import _engine

    if _engine is not None:
        _engine.dispose()


@pytest.fixture
def workspace(_isolated_env):
    return _isolated_env


@pytest.fixture
def sample_graph_path(tmp_path):
    src = Path(__file__).parent.parent / "examples" / "sample_project" / "task_graph.json"
    dst = tmp_path / "task_graph.json"
    shutil.copy2(src, dst)
    return dst
