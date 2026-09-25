"""OpenAIBackend integration tests against a local OpenAI-compatible stub.

The remaining unverified surface before "real production" was the real-LLM
success path: no OPENAI_API_KEY exists in this environment, so it had never
been exercised (coverage 77%). These tests spin up a minimal /chat/completions
HTTP server and drive OpenAIBackend through its success, malformed-payload,
untrusted-path and network-failure branches - proving the parser, the
worktree write-into-isolation and the fail->failed-attempt contract without
any external service.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from factory.agents.base import AgentInput
from factory.agents.coder import OpenAIBackend

openai = pytest.importorskip("openai")


class _Quiet(ThreadingHTTPServer):
    daemon_threads = True


class _StubHandler(BaseHTTPRequestHandler):
    payload = "{}"
    status_code = 200

    def do_POST(self):  # noqa: N802
        content = (self.payload or "").encode("utf-8")
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.status_code == 200:
            self.wfile.write(content)
        else:
            self.wfile.write(b'{"error": {"message": "boom"}}')

    def log_message(self, *args):  # noqa: D102
        pass


_ALIVE_CHECK = False


@pytest.fixture
def llm_stub(monkeypatch):
    """Start a throwaway OpenAI-compatible server; monkeypatch env so
    OpenAIBackend points at it (no real key or network needed)."""
    server = _Quiet(("127.0.0.1", 0), _StubHandler)

    def _serve():
        server.serve_forever(poll_interval=0.05)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    port = server.server_address[1]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("OPENAI_MODEL", "stub-model")
    yield server
    server.shutdown()


def _task(tmp_path, goal="build a module") -> AgentInput:
    return AgentInput(
        agent="coder",
        project_id="p_stub",
        task_id="T001",
        goal=goal,
        acceptance_criteria=["all tests pass"],
        workdir=str(tmp_path),
    )


def _set_payload(server, data: str, status: int = 200, usage: dict | None = None):
    body = {
        "id": "cmpl-stub",
        "object": "chat.completion",
        "created": 0,
        "model": "stub",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": data},
             "finish_reason": "stop"}
        ],
    }
    if usage is not None:
        body["usage"] = usage
    _StubHandler.payload = json.dumps(body) if status == 200 else ""
    _StubHandler.status_code = status


def test_openai_success_writes_files_into_isolation(tmp_path, llm_stub):
    _set_payload(
        llm_stub,
        '```json {"files": {"app/mod.py": "print(1)",'
        ' "tests/test_mod.py": "def test_x():\\n    assert True"}}',
    )
    backend = OpenAIBackend()
    out = backend.run(_task(tmp_path))
    assert out.status == "completed"
    assert set(out.artifacts) == {"app/mod.py", "tests/test_mod.py"}
    assert (tmp_path / "app" / "mod.py").read_text(encoding="utf-8") == "print(1)"
    assert (tmp_path / "tests" / "test_mod.py").exists()


def test_openai_usage_tokens_propagate_to_output(tmp_path, llm_stub):
    """The REAL provider usage must reach the AgentOutput so the
    orchestrator can charge it instead of len(summary) - the P1 billing
    fix. An upstream that omits usage leaves usage_tokens None (fallback)."""
    _set_payload(
        llm_stub,
        '{"files": {"app/mod.py": "print(1)"}}',
        usage={"prompt_tokens": 77, "completion_tokens": 23, "total_tokens": 100},
    )
    out = OpenAIBackend().run(_task(tmp_path))
    assert out.status == "completed"
    assert out.usage_tokens == 100

    # no usage block in the response -> None -> heuristic fallback
    _set_payload(llm_stub, '{"files": {"app/mod.py": "print(1)"}}')
    out2 = OpenAIBackend().run(_task(tmp_path))
    assert out2.usage_tokens is None


def test_openai_malformed_content_is_failed_attempt(tmp_path, llm_stub):
    _set_payload(llm_stub, "this is not json at all")
    out = OpenAIBackend().run(_task(tmp_path))
    assert out.status == "failed"
    assert "invalid JSON" in out.summary


def test_openai_untrusted_path_aborts_batch_writes_nothing(tmp_path, llm_stub):
    _set_payload(llm_stub, '{"files": {"../escape.py": "evil", "ok.py": "fine"}}')
    out = OpenAIBackend().run(_task(tmp_path))
    assert out.status == "failed"
    assert "unsafe path" in out.summary
    assert not (tmp_path / "escape.py").exists()
    assert not (tmp_path / "ok.py").exists()  # whole batch refused


def test_openai_network_error_becomes_failed_attempt_not_crash(tmp_path, llm_stub):
    _set_payload(llm_stub, "", status=500)
    out = OpenAIBackend().run(_task(tmp_path))
    assert out.status == "failed"
    assert "LLM backend error" in out.summary
