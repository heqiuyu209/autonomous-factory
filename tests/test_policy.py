"""Policy engine tests: least privilege enforcement."""
from __future__ import annotations

import pytest

from factory.policy import PolicyEngine, PolicyViolation


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


def test_coder_may_touch_worktree(engine, tmp_path):
    worktree = tmp_path / "task7"
    engine.check_filesystem("coder", worktree / "sample_app" / "calc.py", worktree)


def test_coder_cannot_escape_worktree(engine, tmp_path):
    worktree = tmp_path / "task7"
    outside = tmp_path / "other" / "task.py"
    with pytest.raises(PolicyViolation):
        engine.check_filesystem("coder", outside, worktree)


def test_coder_has_no_internet(engine):
    with pytest.raises(PolicyViolation):
        engine.check_internet("coder", "api.github.com")


def test_market_scout_allowlist(engine):
    engine.check_internet("market-scout", "www.reddit.com")
    with pytest.raises(PolicyViolation):
        engine.check_internet("market-scout", "api.stripe.com")


def test_secrets_denied_for_coder(engine):
    with pytest.raises(PolicyViolation, match="NO secrets access"):
        engine.check_secrets("coder", "prod_db_password")


def test_production_and_billing_denied_by_default(engine):
    with pytest.raises(PolicyViolation):
        engine.assert_production("coder")
    with pytest.raises(PolicyViolation):
        engine.assert_billing("devops")


def test_unknown_agent_gets_least_privilege(engine):
    cap = engine.capability_for("ghost")
    # unknown roles fall back to the factory default: worktree only, no internet.
    assert cap.internet == ()
    assert cap.filesystem == ("{worktree}",)
    assert not cap.production and not cap.billing
