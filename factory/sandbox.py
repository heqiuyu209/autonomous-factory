"""Verifier sandboxing - OS-level isolation for untrusted LLM output.

The factory runs code written by an LLM backend. That output is
UNTRUSTED: it can read files, exfiltrate credentials, delete data or
drive the host network. The reviewer must never execute it on the host
as-is. Every verifier gate therefore runs through a SandboxRunner:

  docker      -> one-shot container: `--network none` (no network at all),
                 `--read-only` rootfs + read-only worktree mount (generated
                 code cannot modify its own source tree), `--cap-drop ALL`
                 and `no-new-privileges` (no kernel privilege escalation),
                 `--tmpfs /tmp` (scratch space), allow-listed environment.
                 This is the production isolation layer (P0).
  subprocess  -> legacy host subprocess with the allow-listed environment
                 and a hard wall-clock timeout. DEGRADED: the code shares
                 the host kernel, filesystem and network; kept only as an
                 explicit fallback for machines without a container runtime.

Policy (fail-closed by default):

  FACTORY_VERIFY_SANDBOX=auto        docker when available, else degraded
                                     subprocess (safe for local demos)
  FACTORY_VERIFY_SANDBOX=docker      docker only; unavailable => refuse to
                                     run any gate (SandboxUnavailableError)
  FACTORY_VERIFY_SANDBOX=subprocess  explicit opt-out, always degraded

Every GateResult carries the sandbox that produced it, so a degraded run
is visible in the report instead of being silently as green as a
containerized one.
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .envsafe import _verifier_env


class SandboxUnavailableError(RuntimeError):
    """The configured sandbox backend cannot run on this host."""


@dataclass
class SandboxResult:
    code: int
    output: str
    backend: str = "subprocess"
    degraded: bool = True


# --------------------------------------------------------------------------
# subprocess (degraded) backend
# --------------------------------------------------------------------------
class SubprocessRunner:
    """Host subprocess with allow-listed env + hard timeout.

    Degraded by design: no kernel / fs / network isolation. The env
    allow-list (shared with the docker backend) is the inner defence layer.
    """

    backend = "subprocess"
    degraded = True

    def run(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: int = 300,
    ) -> SandboxResult:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_verifier_env(),
        )
        tail = (proc.stdout or "")[-2000:] + "\n" + (proc.stderr or "")[-2000:]
        return SandboxResult(proc.returncode, tail, self.backend, self.degraded)


# --------------------------------------------------------------------------
# docker backend (production isolation)
# --------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _docker_available() -> bool:
    from shutil import which

    if which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        # CLI present is NOT enough: the daemon must actually answer.
        # docker info returns non-zero when the engine is down (Docker
        # Desktop stopped, etc.), and selecting docker then would fail
        # every gate. Treat a non-zero probe as unavailable.
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class DockerRunner:
    """One-shot, networkless, read-only container per gate execution.

    The worktree is mounted read-only; scratch goes to /tmp (tmpfs).
    Interpreter scratch (pyc / mypy / pytest caches) is redirected to
    /tmp so read-only mounts cannot break ordinary toolchains.
    """

    backend = "docker"
    degraded = False

    def __init__(self, image: str = "python:3.11-slim"):
        self._image = image
        self._available_cache: Optional[bool] = None

    def available(self) -> bool:
        if self._available_cache is None:
            self._available_cache = _docker_available()
        return self._available_cache

    def _env_file(self, base: dict[str, str]) -> Path:
        """Materialize the allow-listed env as a docker --env-file.

        Container-specific overrides are appended so toolchains keep their
        scratch off the read-only worktree."""
        env = dict(base)
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
        env.setdefault("MYPY_CACHE_DIR", "/tmp/mypy_cache")
        env.setdefault("RUFF_CACHE_DIR", "/tmp/ruff_cache")
        fd, name = tempfile.mkstemp(prefix="factory_env_", suffix=".env")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for k, v in env.items():
                fh.write(f"{k}={v}\n")
        return Path(name)

    def _run_cmd(
        self,
        cmd: list[str],
        cwd: Path,
        env_file: Path,
    ) -> list[str]:
        # Gate commands are built for the host: they embed the host's
        # sys.executable. Inside the container that path does not exist, so
        # translate it to the interpreter on the image PATH.
        cmd = [("python" if part == sys.executable else part) for part in cmd]
        label = f"factory_verifier={uuid.uuid4().hex}"
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp",
            "--label",
            label,
            "--env-file",
            str(env_file),
            "-v",
            f"{cwd}:/work:ro",
            "-w",
            "/work",
            self._image,
        ] + cmd

    def _cleanup(self, label: str) -> None:
        """Best-effort kill of containers left by a hard timeout."""
        try:
            out = subprocess.run(
                ["docker", "ps", "-q", "--filter", f"label={label}"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            ).stdout.strip()
        except subprocess.SubprocessError:
            return
        for cid in out.splitlines():
            subprocess.run(
                ["docker", "rm", "-f", cid],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

    def run(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: int = 300,
    ) -> SandboxResult:
        if not self.available():
            raise SandboxUnavailableError(
                "FACTORY_VERIFY_SANDBOX=docker but the docker CLI is not "
                "usable on this host; refusing to run gates without "
                "container isolation"
            )
        env_file = self._env_file(_verifier_env())
        docker_cmd = self._run_cmd(cmd, cwd, env_file)
        label = docker_cmd[docker_cmd.index("--label") + 1]
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self._cleanup(label)
            raise
        finally:
            try:
                env_file.unlink(missing_ok=True)
            except OSError:
                pass
        tail = (proc.stdout or "")[-2000:] + "\n" + (proc.stderr or "")[-2000:]
        return SandboxResult(proc.returncode, tail, self.backend, self.degraded)


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------
def get_runner(mode: str | None = None) -> "SandboxRunner":
    """Return the sandbox backend for the configured mode.

    auto: docker when usable, else degraded subprocess.
    docker: docker only; fail closed if unavailable.
    subprocess: degraded host subprocess (explicit opt-out).
    """
    if mode is None:
        mode = os.getenv("FACTORY_VERIFY_SANDBOX", "auto")
    mode = (mode or "auto").lower()
    if mode == "docker":
        runner = DockerRunner()
        if not runner.available():
            raise SandboxUnavailableError(
                "FACTORY_VERIFY_SANDBOX=docker but the docker CLI is not "
                "usable on this host; refusing to run gates without "
                "container isolation"
            )
        return runner
    if mode == "subprocess":
        return SubprocessRunner()
    if mode == "auto":
        runner = DockerRunner()
        if runner.available():
            return runner
        return SubprocessRunner()
    raise ValueError(f"unknown sandbox mode {mode!r} (auto|docker|subprocess)")


SandboxRunner = SubprocessRunner | DockerRunner
