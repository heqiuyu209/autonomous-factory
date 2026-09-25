"""Phase-0 security-fix regressions (P1/P0 remaining items).

Covers:
    * verifier subprocess env isolation - untrusted code runs WITHOUT
      host secrets (OPENAI_API_KEY etc. must not be inherited)
    * orchestrator billing uses real provider usage when available
    * orchestrator feeds the coder the full design context
      (TaskDef.description, dependency summaries, project PRD)
"""
from __future__ import annotations

import sys
from pathlib import Path

from factory.agents.base import AgentInput
from factory.agents.coder import RecipeBackend
from factory.envsafe import _VERIFIER_SAFE_ENV_KEYS, _verifier_env
from factory.orchestrator import FactoryOrchestrator
from factory.schemas.base import AgentOutput
from factory.schemas.task_graph import TaskGraph


# --------------------------------------------------------------------------
# P0: verifier runs untrusted code without host secrets
# --------------------------------------------------------------------------
def test_verifier_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\bin;C:\Windows\System32")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/factory")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("MY_TOKEN_VAR", "tok")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setenv("TMP", r"C:\Users\test\AppData\Local\Temp")

    env = _verifier_env()

    # allow-list essentials survive
    assert env["PATH"] == r"C:\bin;C:\Windows\System32"
    assert env["TMP"] == r"C:\Users\test\AppData\Local\Temp"
    assert env["PYTHONIOENCODING"] == "utf-8"
    # secrets are gone - even a key whose NAME looks sensitive
    assert "OPENAI_API_KEY" not in env
    assert "DATABASE_URL" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "MY_TOKEN_VAR" not in env
    # nothing unexpected leaked: every key is allow-listed
    assert all(
        k in _VERIFIER_SAFE_ENV_KEYS or k.upper().startswith("PYTHON")
        for k in env
    )


def test_verifier_gate_subprocess_gets_clean_env(monkeypatch, tmp_path):
    """End-to-end: a gate subprocess cannot see a host secret even when the
    untrusted code deliberately tries to read it."""
    from factory.sandbox import SubprocessRunner
    from factory.verifier import Verifier, _run

    monkeypatch.setenv("OPENAI_API_KEY", "sk-injected-secret")
    workdir = tmp_path / "w"
    workdir.mkdir()
    (workdir / "leak.py").write_text(
        "import os\n"
        "p = os.environ.get('OPENAI_API_KEY')\n"
        "assert p is None, f'leaked: {p}'\n",
        encoding="utf-8",
    )
    (workdir / "test_leak.py").write_text(
        "import os\n"
        "def test_no_secret():\n"
        "    assert os.environ.get('OPENAI_API_KEY') is None\n",
        encoding="utf-8",
    )
    v = Verifier(runner=SubprocessRunner(), gates=("syntax", "test"))
    code, _out, _sbx = _run(
        v,
        [sys.executable, "-c", "import os; assert os.environ.get('OPENAI_API_KEY') is None"],
        workdir,
    )
    assert code == 0
    results = v.run_all(workdir)
    assert v.summarize(results)["passed"]


# --------------------------------------------------------------------------
# P1: real token billing
# --------------------------------------------------------------------------
def test_charged_tokens_prefers_real_usage():
    orch = FactoryOrchestrator(workspace_root=Path("."))
    real = AgentOutput(summary="x" * 500, usage_tokens=42)
    assert orch._charged_tokens(real) == 42
    unknown = AgentOutput(summary="abc")
    assert orch._charged_tokens(unknown) == 3


# --------------------------------------------------------------------------
# P1: coder receives full design context
# --------------------------------------------------------------------------
class _CaptureBackend:
    """Writes the standard recipe files (so the pipeline stays green) and
    records every AgentInput it received. The orchestrator runs coder
    attempts in a spawned process (hard-timeout isolation), so in-memory
    state never comes back to the parent: we append to a JSONL file
    instead, and the test reads that file back."""

    name = "capture"
    backend = None  # _maybe_strip_seed checks coder.backend on repair paths

    def __init__(self, log_path: Path):
        self._log = log_path

    def run(self, task: AgentInput) -> AgentOutput:
        with self._log.open("a", encoding="utf-8") as fh:
            fh.write(
                __import__("json").dumps(
                    {
                        "task_id": task.task_id,
                        "description": task.description,
                        "deps": task.context.get("deps", []),
                        "prd": task.context.get("prd", ""),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return RecipeBackend(inject_bug=False).run(task)


def test_orchestrator_injects_description_deps_prd(
    workspace, sample_graph_path, monkeypatch
):
    """A dependent task's coder must see: its own TaskDef.description, the
    dependency task's summary, and the project PRD text."""
    import json

    graph = TaskGraph.load(sample_graph_path)
    from factory.sandbox import SubprocessRunner
    from factory.verifier import Verifier

    orch = FactoryOrchestrator(
        workspace_root=workspace,
        verifier=Verifier(
            runner=SubprocessRunner(),
            gates=("syntax", "test", "lint"),
        ),
    )
    log = workspace / "capture.jsonl"
    backend = _CaptureBackend(log)
    # deterministic backend; no seed bug so the run is a single pass
    from factory.agents import AgentRegistry

    registry = AgentRegistry.default()
    registry.register("coder", backend)
    orch.registry = registry

    prd = workspace / "prd.md"
    prd.write_text("# Product: sample calc service\nDesign intent line.", encoding="utf-8")
    monkeypatch.chdir(workspace)

    report = orch.run_graph(
        project_id=graph.project_id,
        name=graph.name,
        graph=graph,
        prd_path="prd.md",
        seed_bug=False,
    )
    assert report["summary"]["state"] == "DONE", report

    captured = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    by_id = {c["task_id"]: c for c in captured}
    # T001 got its own description, not just the title
    assert "seeded with a defect" in by_id["T001"]["description"]
    # T002's deps context shows what T001 actually produced
    deps = by_id["T002"]["deps"]
    assert [d["task_id"] for d in deps] == ["T001"]
    assert deps[0]["summary"] == "implemented sample_app package with unit tests"
    assert deps[0]["artifacts"]
    # PRD text reaches the coder
    assert "Design intent line" in by_id["T002"]["prd"]
    assert "Design intent line" in by_id["T001"]["prd"]
