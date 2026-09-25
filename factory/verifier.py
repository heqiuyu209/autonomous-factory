"""Machine Verifier - deterministic verification pipeline (blueprint §11, §14).

The LLM reviewer never holds final decision power. Before any code is
approved, a deterministic pipeline must be green:

    format -> lint -> typecheck -> build -> unit tests -> integration
    -> E2E -> security -> dependency scan -> performance

V1 ships the gates that run anywhere (syntax, unit tests, lint when the
tool is installed); heavier gates are registered but report SKIPPED, and
the framework makes adding a gate a one-function change.

Every gate runs inside a SandboxRunner (factory.sandbox): container
isolation (networkless, read-only) when available, or a degraded
allow-listed subprocess otherwise. The backend is recorded per gate so a
degraded verification is never mistaken for a containerized one.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .envsafe import _verifier_env  # noqa: F401  (re-exported for tests)
from .sandbox import SandboxResult, SandboxRunner, get_runner


@dataclass
class GateResult:
    gate: str
    passed: bool
    output: str = ""
    skipped: bool = False
    sandbox: str = "subprocess"
    degraded: bool = True

    def as_dict(self) -> dict:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "skipped": self.skipped,
            "output": self.output[:4000],
            "sandbox": self.sandbox,
            "degraded": self.degraded,
        }


GateFn = Callable[[Path, "Verifier"], GateResult]


def _run(
    v: "Verifier",
    cmd: list[str],
    workdir: Path,
    timeout: int = 300,
) -> tuple[int, str, SandboxResult]:
    result = v.runner.run(cmd, workdir, timeout=timeout)
    return result.code, result.output, result


# --------------------------------------------------------------------------
# Gate implementations
# --------------------------------------------------------------------------
def _result(
    v: "Verifier",
    name: str,
    passed: bool,
    out: str,
    skipped: bool = False,
) -> GateResult:
    return GateResult(
        name,
        passed,
        out,
        skipped=skipped,
        sandbox=v.runner.backend,
        degraded=v.runner.degraded,
    )


def gate_syntax(workdir: Path, v: "Verifier") -> GateResult:
    py_files = sorted(workdir.rglob("*.py"))
    # ignore vendored/venv dirs
    py_files = [p for p in py_files if ".venv" not in p.parts]
    if not py_files:
        # a legitimately non-code task (docs / config / data) is not a
        # syntax failure - mirror the unit-tests gate's SKIP semantics.
        return _result(
            v, "syntax", True, "no python files in this worktree; skipped", skipped=True
        )
    # -B: never write .pyc. The worktree is mounted read-only in the docker
    # sandbox; py_compile must not try to write next to the sources.
    cmd = [sys.executable, "-B", "-m", "py_compile"] + [str(p) for p in py_files]
    code, out, _sbx = _run(v, cmd, workdir)
    return _result(v, "syntax", code == 0, out)


def gate_unit_tests(workdir: Path, v: "Verifier") -> GateResult:
    if not _test_files(workdir):
        # no tests in this slice yet - e.g. scaffold-only task in a DAG.
        return _result(
            v, "unit-tests", True, "no tests in this worktree; skipped", skipped=True
        )
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
    code, out, _sbx = _run(v, cmd, workdir, timeout=600)
    return _result(v, "unit-tests", code == 0, out)


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


def gate_lint(workdir: Path, v: "Verifier") -> GateResult:
    if _tool_exists("ruff"):
        # --isolated --no-cache: a DETERMINISTIC verification gate. Without
        # --isolated, ruff walks up from the worktree to find a pyproject /
        # ruff config; a worktree under the project root inherits the host
        # project's isort settings while one outside it falls back to the
        # defaults - two different lint semantics for identical bytes, so a
        # task that passes in a scratch dir can fail under the real runtime
        # and vice versa. --isolated pins ONE semantics everywhere, and
        # --no-cache prevents stale on-disk cache verdicts from flipping
        # green/red across runs. Verdicts must depend only on the code.
        code, out, _sbx = _run(
            v, ["ruff", "check", "--isolated", "--no-cache", "."], workdir
        )
        return _result(v, "lint", code == 0, out)
    if _tool_exists("flake8"):
        code, out, _sbx = _run(v, ["flake8", "--isolated", "."], workdir)
        return _result(v, "lint", code == 0, out)
    return _result(v, "lint", True, "lint tool not installed; skipped", skipped=True)


def gate_typecheck(workdir: Path, v: "Verifier") -> GateResult:
    if _tool_exists("mypy"):
        code, out, _sbx = _run(v, ["mypy", "."], workdir)
        return _result(v, "typecheck", code == 0, out)
    return _result(v, "typecheck", True, "mypy not installed; skipped", skipped=True)


def _tool_exists(name: str) -> bool:
    from shutil import which

    return which(name) is not None


class Verifier:
    """Runs configured gates in order; any failure blocks the merge.

    `runner` is the SandboxRunner every gate executes under (container
    isolation or degraded allow-listed subprocess). A runner is resolved
    once at construction so a whole verification uses one consistent
    isolation level, and so a missing mandatory container fails loudly
    before any gate runs.
    """

    def __init__(
        self,
        gates: tuple[str, ...] | None = None,
        runner: "SandboxRunner" | None = None,
    ):
        self._registry: dict[str, GateFn] = {
            "syntax": gate_syntax,
            "test": gate_unit_tests,
            "lint": gate_lint,
            "typecheck": gate_typecheck,
        }
        self._gates = gates or ("syntax", "test")
        self.runner = runner if runner is not None else get_runner()
        self.backend = self.runner.backend
        self.degraded = self.runner.degraded

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
                        sandbox=self.backend,
                        degraded=self.degraded,
                    )
                )
                break
            try:
                results.append(self._registry[name](workdir, self))
            except Exception as exc:  # pragma: no cover - defensive
                results.append(
                    GateResult(
                        name,
                        False,
                        repr(exc),
                        sandbox=self.backend,
                        degraded=self.degraded,
                    )
                )
            if not results[-1].passed and not results[-1].skipped:
                break  # fail-fast: no point running the rest on a broken tree
        return results

    def summarize(self, results: list[GateResult]) -> dict:
        return {
            "passed": all(r.passed or r.skipped for r in results),
            "gates": [r.as_dict() for r in results],
            "sandbox": {
                "backend": self.backend,
                "degraded": self.degraded,
            },
        }
