"""Budget tracker (blueprint §25).

Keeps spend under a shared budget for tokens and USD; every charge is
recorded to the ledger so spend is auditable, and the factory halts
(never silently continues) when the budget is exhausted.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    def __init__(self, account: str, limit: float, attempted: float):
        super().__init__(
            f"budget exceeded for '{account}': limit={limit} < remaining+attempted"
        )
        self.account = account
        self.limit = limit
        self.attempted = attempted


@dataclass
class BudgetTracker:
    """In-memory tracker; durable ledger lives in the DB (BudgetLedger)."""

    limit_tokens: float = float("inf")
    limit_usd: float = float("inf")
    limit_runtime_s: float = float("inf")
    spent_tokens: float = 0.0
    spent_usd: float = 0.0
    spent_runtime_s: float = 0.0
    entries: list[dict] = field(default_factory=list)

    @classmethod
    def from_limits(
        cls,
        tokens: float,
        usd: float = float("inf"),
        runtime_s: float = float("inf"),
    ) -> "BudgetTracker":
        return cls(
            limit_tokens=tokens, limit_usd=usd, limit_runtime_s=runtime_s
        )

    @property
    def remaining_usd(self) -> float:
        return self.limit_usd - self.spent_usd

    @property
    def remaining_tokens(self) -> float:
        return self.limit_tokens - self.spent_tokens

    @property
    def remaining_runtime_s(self) -> float:
        return self.limit_runtime_s - self.spent_runtime_s

    def check(
        self, tokens: float = 0.0, usd: float = 0.0, runtime_s: float = 0.0
    ) -> None:
        if self.spent_tokens + tokens > self.limit_tokens:
            raise BudgetExceeded(
                "tokens", self.limit_tokens, self.spent_tokens + tokens
            )
        if self.spent_usd + usd > self.limit_usd:
            raise BudgetExceeded("usd", self.limit_usd, self.spent_usd + usd)
        if self.spent_runtime_s + runtime_s > self.limit_runtime_s:
            raise BudgetExceeded(
                "runtime_s",
                self.limit_runtime_s,
                self.spent_runtime_s + runtime_s,
            )

    def charge(
        self,
        tokens: float = 0.0,
        usd: float = 0.0,
        agent: str = "",
        note: str = "",
    ) -> None:
        self.check(tokens, usd)
        self.spent_tokens += tokens
        self.spent_usd += usd
        self.entries.append(
            {
                "id": uuid.uuid4().hex[:12],
                "agent": agent,
                "tokens": tokens,
                "usd": usd,
                "runtime_s": 0.0,
                "note": note,
            }
        )

    def charge_runtime(self, seconds: float, agent: str = "", note: str = "") -> None:
        """Charge wall-clock seconds spent by an agent against the runtime
        budget. A slow or hung agent must halt the task, never silently
        stretch past its ceiling."""
        self.check(runtime_s=seconds)
        self.spent_runtime_s += seconds
        self.entries.append(
            {
                "id": uuid.uuid4().hex[:12],
                "agent": agent,
                "tokens": 0.0,
                "usd": 0.0,
                "runtime_s": round(seconds, 3),
                "note": note,
            }
        )
