"""Verifier configuration-contract tests: gates are fail-closed.

A verification gate that was never implemented (typo in
FACTORY_VERIFY_GATES, or a gate name missing from the registry) must NEVER
report green - "we verified" when we did not is a false assurance that
would let a broken build sail through CI.
"""
from __future__ import annotations

from pathlib import Path

from factory.orchestrator import FactoryOrchestrator
from factory.verifier import Verifier


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_unknown_gate_fail_closed(tmp_path):
    """A missing gate must FAIL, not silently pass."""
    wd = _tree(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "def test_trivial():\n    assert True\n",
        },
    )
    v = Verifier(gates=("syntax", "test", "security"))
    results = v.run_all(wd)
    assert not v.summarize(results)["passed"]
    assert results[-1].gate == "security"
    assert not results[-1].passed
    assert not results[-1].skipped


def test_unknown_gate_hits_fail_fast_stop(tmp_path):
    """Fail-fast: a missing gate halts the pipeline before later gates run."""
    wd = _tree(tmp_path, {"app/ok.py": "x = 1\n"})
    v = Verifier(gates=("syntax", "nonsense", "test"))
    results = v.run_all(wd)
    assert [g.gate for g in results] == ["syntax", "nonsense"]
    assert not v.summarize(results)["passed"]


def test_unknown_gate_reports_registry(tmp_path):
    """The error must tell the operator which gates are actually available."""
    wd = _tree(tmp_path, {"app/ok.py": "x = 1\n"})
    v = Verifier(gates=("bogus",))
    results = v.run_all(wd)
    assert "registered" in results[0].output.lower()


def test_orchestrator_reads_settings_gates(tmp_path):
    """Regression: FACTORY_VERIFY_GATES must reach the verifier, not a
    hard-coded default."""
    from factory.config import settings

    orch = FactoryOrchestrator(workspace_root=tmp_path / "ws")
    assert orch.verifier._gates == tuple(settings.verify_gates)
