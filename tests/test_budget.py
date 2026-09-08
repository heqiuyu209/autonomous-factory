"""Budget tracker tests."""
from __future__ import annotations

import pytest

from factory.budget import BudgetExceeded, BudgetTracker


def test_charge_and_remaining():
    b = BudgetTracker.from_limits(tokens=1000, usd=10)
    b.charge(tokens=300, usd=3, agent="coder")
    assert b.spent_tokens == 300
    assert b.spent_usd == 3
    assert b.remaining_tokens == 700


def test_exceeded_raises():
    b = BudgetTracker.from_limits(tokens=100, usd=1)
    with pytest.raises(BudgetExceeded):
        b.charge(tokens=200, usd=0.5)


def test_ledger_records_agent():
    b = BudgetTracker.from_limits(tokens=100, usd=1)
    b.charge(tokens=10, usd=0.1, agent="reviewer", note="review pass")
    assert b.entries[0]["agent"] == "reviewer"
