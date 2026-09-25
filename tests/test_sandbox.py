"""P0: verifier sandbox - container isolation for untrusted LLM output.

Covers:
    * subprocess runner is the degraded fallback (allow-listed env)
    * docker runner command shape: networkless, read-only, no caps,
      no-new-privileges, tmpfs scratch, allow-listed env-file
    * docker-unavailable fails closed when docker is the configured mode
    * auto mode degrades to subprocess (never crashes the pipeline)
    * every GateResult / summary carries the sandbox that produced it
"""
from __future__ import annotations

import sys

import pytest

from factory.sandbox import (
    DockerRunner,
    SandboxUnavailableError,
    SubprocessRunner,
    get_runner,
)
from factory.verifier import Verifier


# --------------------------------------------------------------------------
# subprocess (degraded) backend
# --------------------------------------------------------------------------
def test_subprocess_runner_is_degraded(tmp_path):
    runner = SubprocessRunner()
    res = runner.run(
        [sys.executable, "-c", "print('ok')"], tmp_path, timeout=60
    )
    assert res.code == 0
    assert "ok" in res.output
    assert res.backend == "subprocess"
    assert res.degraded is True


def test_subprocess_runner_still_strips_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-injected")
    runner = SubprocessRunner()
    res = runner.run(
        [
            sys.executable,
            "-c",
            "import os; assert os.environ.get('OPENAI_API_KEY') is None",
        ],
        tmp_path,
        timeout=60,
    )
    assert res.code == 0


# --------------------------------------------------------------------------
# docker backend
# --------------------------------------------------------------------------
def test_docker_command_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "factory.sandbox._docker_available", lambda: True
    )
    runner = DockerRunner(image="python:3.11-slim")
    env_file = tmp_path / "env.env"
    env_file.write_text("PATH=/bin\n", encoding="utf-8")
    cmd = runner._run_cmd(["/work/x.py"], tmp_path, env_file)

    joined = " ".join(cmd)
    # no network at all
    assert "--network none" in joined
    # root filesystem read-only AND the worktree mounted read-only
    assert "--read-only" in joined
    assert f"{tmp_path}:/work:ro" in joined
    # no kernel privilege escalation
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    # scratch space
    assert "--tmpfs /tmp" in joined
    # allow-listed environment via env-file, pinned image
    assert "--env-file" in joined
    assert "python:3.11-slim" in joined
    # the actual command is the payload
    assert cmd[-1] == "/work/x.py"
    assert "/work" in cmd[cmd.index("-w") + 1]

    # gate commands embed the HOST interpreter; inside the container that
    # path does not exist, so it must be translated to the image PATH
    py_cmd = runner._run_cmd([sys.executable, "-m", "pytest"], tmp_path, env_file)
    assert py_cmd[py_cmd.index("python:3.11-slim") + 1] == "python"
    assert sys.executable not in py_cmd


def test_docker_env_file_redirects_scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "factory.sandbox._docker_available", lambda: True
    )
    runner = DockerRunner()
    lines = runner._env_file({"PATH": "/bin"}).read_text(encoding="utf-8")
    assert "PYTHONDONTWRITEBYTECODE=1" in lines
    assert "MYPY_CACHE_DIR=/tmp/mypy_cache" in lines
    assert "RUFF_CACHE_DIR=/tmp/ruff_cache" in lines
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in lines


# --------------------------------------------------------------------------
# selection & fail-closed policy
# --------------------------------------------------------------------------
def test_get_runner_mode_subprocess_is_explicit_opt_out():
    runner = get_runner("subprocess")
    assert isinstance(runner, SubprocessRunner)


def test_get_runner_mode_docker_unavailable_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "factory.sandbox._docker_available", lambda: False
    )
    with pytest.raises(SandboxUnavailableError):
        get_runner("docker")


def test_get_runner_auto_degrades_to_subprocess(monkeypatch):
    monkeypatch.setattr(
        "factory.sandbox._docker_available", lambda: False
    )
    runner = get_runner("auto")
    assert isinstance(runner, SubprocessRunner)
    assert runner.degraded is True


def test_verifier_docker_mode_unavailable_fails_closed(monkeypatch):
    """Verifier construction resolves the sandbox; a mandatory container
    that cannot run must refuse to verify at all (fail closed)."""
    monkeypatch.setattr(
        "factory.sandbox._docker_available", lambda: False
    )
    with pytest.raises(SandboxUnavailableError):
        Verifier(runner=get_runner("docker"))


# --------------------------------------------------------------------------
# verifier reports the sandbox it used
# --------------------------------------------------------------------------
def test_verifier_gates_record_sandbox(tmp_path):
    workdir = tmp_path / "w"
    workdir.mkdir()
    (workdir / "ok.py").write_text("x = 1\n", encoding="utf-8")
    v = Verifier(runner=SubprocessRunner(), gates=("syntax",))
    results = v.run_all(workdir)
    summary = v.summarize(results)

    assert summary["passed"] is True
    assert summary["sandbox"] == {"backend": "subprocess", "degraded": True}
    gate = summary["gates"][0]
    assert gate["sandbox"] == "subprocess"
    assert gate["degraded"] is True
