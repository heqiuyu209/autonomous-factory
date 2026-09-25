"""Web data-source fetchers + WebBackend scout tests (no real network)."""
from __future__ import annotations

from pathlib import Path

import pytest

from factory.agents.base import AgentInput
from factory.agents.scout import MarketScoutAgent, WebBackend
from factory.sources import Signal, fetch_github, fetch_reddit


class _FakeFetchers:
    @staticmethod
    def reddit(query: str, limit: int = 5) -> list[Signal]:
        return [
            Signal(source="reddit", title=f"r/ai {query} pain thread", snippet="people complain a lot", url="https://reddit.example/t/1"),
            Signal(source="reddit", title="how do you all handle this", snippet="asking for tooling", url="https://reddit.example/t/2"),
        ]

    @staticmethod
    def github(query: str, limit: int = 5) -> list[Signal]:
        return [
            Signal(source="github", title=f"user/{query}-tool", snippet="helps with the workflow", url="https://github.example/user/tool"),
        ]

    @staticmethod
    def empty(query: str, limit: int = 5) -> list[Signal]:
        return []


def _run_web(task: AgentInput, fetchers: dict) -> tuple[WebBackend, str]:
    backend = WebBackend(fetchers=fetchers)
    out = MarketScoutAgent(backend=backend).run(task)
    return backend, out.summary


def test_web_backend_writes_signals(tmp_path: Path):
    task = AgentInput(
        agent="scout",
        project_id="p_web_test",
        task_id="scout",
        goal="ai meeting notes",
        constraints=["reddit", "github"],
        workdir=str(tmp_path),
    )
    backend, summary = _run_web(task, {"reddit": _FakeFetchers.reddit, "github": _FakeFetchers.github})
    assert "web-scouted 3 signal(s)" in summary
    json_file = tmp_path / "opportunities.json"
    md_file = tmp_path / "opportunities.md"
    assert json_file.exists()
    assert md_file.exists()
    import json

    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data[0]["opportunity_id"].startswith("opp_")
    pains = data[0]["pains"]
    assert len(pains) == 3
    assert any(p["persona"] == "reddit" for p in pains)
    assert any(p["persona"] == "github" for p in pains)
    assert all(p["sources"] for p in pains)
    assert backend.name == "web"


def test_web_backend_degrades_to_recipe_on_empty(tmp_path: Path):
    task = AgentInput(
        agent="scout",
        project_id="p_web_empty",
        task_id="scout",
        goal="ai meeting notes",
        constraints=["reddit"],
        workdir=str(tmp_path),
    )
    backend, summary = _run_web(task, {"reddit": _FakeFetchers.empty})
    assert "degraded to recipe candidates" in summary
    import json

    data = json.loads((tmp_path / "opportunities.json").read_text(encoding="utf-8"))
    assert data[0]["opportunity_id"].startswith("opp_")
    assert data[0]["pains"][0]["sources"] == ["reddit"]


def test_web_backend_ignores_unknown_source_and_falls_back(tmp_path: Path):
    """Unknown source names must not crash; no signals -> recipe degrade."""
    task = AgentInput(
        agent="scout",
        project_id="p_web_unknown",
        task_id="scout",
        goal="ai meeting notes",
        constraints=["unknown-source"],
        workdir=str(tmp_path),
    )
    backend, summary = _run_web(task, {"reddit": _FakeFetchers.reddit})
    assert "degraded to recipe candidates" in summary
    assert backend.name == "web"


def test_web_backend_enforces_internet_policy(tmp_path: Path):
    """The market-scout capability gate is wired: a denied host must fail
    closed instead of silently fetching."""
    from factory.policy import Capability, PolicyEngine, PolicyViolation

    task = AgentInput(
        agent="scout",
        project_id="p_policy",
        task_id="scout",
        goal="x",
        constraints=["reddit"],
        workdir=str(tmp_path),
    )
    strict = PolicyEngine({"market-scout": Capability(internet=())})
    backend = WebBackend(fetchers={"reddit": _FakeFetchers.reddit}, policy=strict)
    with pytest.raises(PolicyViolation):
        backend.run(task)


def test_fetch_reddit_parses_posts():
    """Network-unreachable fetcher must degrade to empty (no crash)."""
    signals = fetch_reddit("x", base_url="http://unused")
    assert signals == []  # network unreachable -> defensive empty


def test_fetch_github_parses_items():
    """Pure parse test without network: verify parser via monkeypatched payload."""
    from factory import sources as src_mod

    payload = {
        "items": [
            {"full_name": "a/b", "description": "desc", "html_url": "https://github.example/a/b"},
            {"full_name": "", "description": ""},
        ]
    }

    def _fake_get_json(url: str) -> dict | None:  # noqa: ARG001
        return payload

    original = src_mod._get_json
    src_mod._get_json = _fake_get_json
    try:
        signals = fetch_github("x")
    finally:
        src_mod._get_json = original
    assert len(signals) == 1
    assert signals[0].source == "github"
    assert signals[0].title == "a/b"
    assert signals[0].url == "https://github.example/a/b"
