"""Verifier pipeline tests."""
from __future__ import annotations

from pathlib import Path

from factory.verifier import Verifier


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_healthy_tree_passes(tmp_path):
    wd = _tree(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from app.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
    )
    v = Verifier(gates=("syntax", "test"))
    results = v.run_all(wd)
    assert v.summarize(results)["passed"]


def test_syntax_error_fails(tmp_path):
    wd = _tree(tmp_path, {"app/broken.py": "def broken(:\n    pass\n"})
    v = Verifier(gates=("syntax",))
    results = v.run_all(wd)
    assert not v.summarize(results)["passed"]
    assert results[0].gate == "syntax"


def test_failing_test_fails(tmp_path):
    wd = _tree(
        tmp_path,
        {
            "app/calc.py": "def add(a, b):\n    return a - b\n",  # wrong on purpose
            "tests/test_calc.py": "from app.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
    )
    v = Verifier(gates=("syntax", "test"))
    results = v.run_all(wd)
    assert not v.summarize(results)["passed"]


def test_relative_workdir_passes(tmp_path, monkeypatch):
    """Regression: gates must work when the worktree is reached via a
    *relative* path (default FACTORY_WORKSPACE is './factory_runtime').
    Previously the relative path leaked into the subprocess and died with
    'No such file or directory'."""
    _tree(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from app.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
    )
    monkeypatch.chdir(tmp_path)
    rel = Path(".")
    v = Verifier(gates=("syntax", "test"))
    results = v.run_all(rel)
    assert v.summarize(results)["passed"]
