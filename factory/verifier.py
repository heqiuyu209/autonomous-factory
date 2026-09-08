"""Machine Verifier - deterministic verification pipeline (blueprint §11, §14).

The LLM reviewer never holds final decision power. Before any code is
approved, a deterministic pipeline must be green:

    format -> lint -> typecheck -> build -> unit tests -> integration
    -> E2E -> security -> dependency scan -> performance

V1 ships the gates that run anywhere (syntax, unit tests, lint when the
tool is installed); heavier gates are registered but report SKIPPED, and
the framework makes adding a gate a one-function change.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class GateResult:
    gate: str
    passed: bool
    output: str = ""
    skipped: bool = False

    def as_dict(self) -> dict:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "skipped": self.skipped,
            "output": self.output[:4000],
        }


GateFn = Callable[[Path, "Verifier"], GateResult]


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    tail = (proc.stdout or "")[-2000:] + "\n" + (proc.stderr or "")[-2000:]
    return proc.returncode, tail


# --------------------------------------------------------------------------
# Gate implementations
# --------------------------------------------------------------------------
def gate_syntax(workdir: Path, _v: "Verifier") -> GateResult:
    py_files = sorted(workdir.rglob("*.py"))
    # ignore vendored/venv dirs
    py_files = [p for p in py_files if ".venv" not in p.parts]
    if not py_files:
        # a legitimately non-code task (docs / config / data) is not a
        # syntax failure - mirror the unit-tests gate's SKIP semantics.
        return GateResult(
            "syntax", True, "no python files in this worktree; skipped", skipped=True
        )
    cmd = [sys.executable, "-m", "py_compile"] + [str(p) for p in py_files]
    code, out = _run(cmd, workdir)
    return GateResult("syntax", code == 0, out)


def gate_unit_tests(workdir: Path, _v: "Verifier") -> GateResult:
    if not _test_files(workdir):
        # no tests in this slice yet - e.g. scaffold-only task in a DAG.
        return GateResult(
            "unit-tests", True, "no tests in this worktree; skipped", skipped=True
        )
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
    code, out = _run(cmd, workdir, timeout=600)
    return GateResult("unit-tests", code == 0, out)


def _test_files(workdir: Path) -> list[Path]:
    """Mirror pytest's discovery loosely: *_test.py / test_*.py anywhere,
    plus any .py under a tests/ directory. An EMPTY tests/ directory is
    NOT a test suite - running pytest on it exits 5 and would falsely
    block a legitimate task."""
    found: list[Path] = []
    for p in workdir.rglob("*.py"):
        if ".venv" in p.parts:
            continue
        if p.name.endswith("_test.py") or p.name.startswith("test_"):
            found.append(p)
        elif "tests" in p.parts:
            found.append(p)
    return found


def gate_lint(workdir: Path, _v: "Verifier") -> GateResult:
    for tool in ("ruff", "flake8"):
        if _tool_exists(tool):
            code, out = _run([tool, "check", "."], workdir)
            return GateResult("lint", code == 0, out)
    return GateResult("lint", True, "lint tool not installed; skipped", skipped=True)


def gate_typecheck(workdir: Path, _v: "Verifier") -> GateResult:
    if _tool_exists("mypy"):
        code, out = _run(["mypy", "."], workdir)
        return GateResult("typecheck", code == 0, out)
    return GateResult("typecheck", True, "mypy not installed; skipped", skipped=True)


def _tool_exists(name: str) -> bool:
    from shutil import which

    return which(name) is not None


class Verifier:
    """Runs configured gates in order; any failure blocks the merge."""

    def __init__(self, gates: tuple[str, ...] | None = None):
        self._registry: dict[str, GateFn] = {
            "syntax": gate_syntax,
            "test": gate_unit_tests,
            "lint": gate_lint,
            "typecheck": gate_typecheck,
        }
        self._gates = gates or ("syntax", "test")

    def register(self, name: str, fn: GateFn) -> None:
        self._registry[name] = fn

    def run_all(self, workdir: Path) -> list[GateResult]:
        results: list[GateResult] = []
        # Resolve once: workspace_root may be a relative path, and the gates
        # hand absolute file paths to subprocesses running with cwd=workdir.
        # A relative workdir would break them with "No such file or directory".
        workdir = Path(workdir).resolve()
        for name in self._gates:
            if name not in self._registry:
                # Gate names are part of the configuration contract. A typo
                # or a not-yet-implemented gate must never report green:
                # "we verified" when we did not is a false assurance. Fail
                # closed and stop the pipeline so the misconfiguration
                # surfaces loudly instead of silently passing.
                results.append(
                    GateResult(
                        name,
                        False,
                        "unknown gate {!r} (registered: {}) - a missing gate "
                        "is a configuration error and refuses to pass; "
                        "check FACTORY_VERIFY_GATES".format(
                            name, sorted(self._registry)
                        ),
                    )
                )
                break
            try:
                results.append(self._registry[name](workdir, self))
            except Exception as exc:  # pragma: no cover - defensive
                results.append(GateResult(name, False, repr(exc)))
            if not results[-1].passed and not results[-1].skipped:
                break  # fail-fast: no point running the rest on a broken tree
        return results

    @property
    def all_green(self) -> bool:
        raise NotImplementedError  # use run_all().  kept for clarity

    def summarize(self, results: list[GateResult]) -> dict:
        return {
            "passed": all(r.passed or r.skipped for r in results),
            "gates": [r.as_dict() for r in results],
        }
