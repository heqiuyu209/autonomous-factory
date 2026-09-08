"""Budget model (blueprint §25).

Every agent/run is charged against an account. Ledger rows make every
spend auditable; when the balance is exhausted the factory stops, it
never silently exceeds a budget.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BudgetAccount(Base):
    __tablename__ = "budget_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))  # project | task | global
    limit_tokens: Mapped[float] = mapped_column(default=0.0)
    limit_usd: Mapped[float] = mapped_column(default=0.0)
    spent_tokens: Mapped[float] = mapped_column(default=0.0)
    spent_usd: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    def remaining(self) -> float:
        return self.limit_usd - self.spent_usd


class BudgetLedger(Base):
    __tablename__ = "budget_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("budget_accounts.id", ondelete="CASCADE"), index=True
    )
    ref_type: Mapped[str] = mapped_column(String(16))  # run | task | agent
    ref_id: Mapped[str] = mapped_column(String(64))
    cost_tokens: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_runtime_s: Mapped[float] = mapped_column(Float, default=0.0)
    agent: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
