"""Application configuration.

Environment-driven, with sensible local defaults.
All secrets must come from the environment - never from code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # --- database -------------------------------------------------------
    # Default to a local file DB for zero-setup demos; switch to PostgreSQL
    # via DATABASE_URL without touching any code.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "FACTORY_DATABASE_URL", "sqlite:///./factory.db"
        )
    )

    # --- runtime workspace ---------------------------------------------
    # Where the factory keeps project worktrees and run artifacts.
    workspace_root: Path = field(
        default_factory=lambda: Path(
            os.getenv("FACTORY_WORKSPACE", "./factory_runtime")
        )
    )

    # --- agent runtime --------------------------------------------------
    # Budget guards (blueprint §25). Per-task ceilings.
    max_coder_retries: int = field(
        default_factory=lambda: int(os.getenv("FACTORY_MAX_RETRIES", "3"))
    )
    default_token_budget: int = field(
        default_factory=lambda: int(os.getenv("FACTORY_TOKEN_BUDGET", "120000"))
    )
    default_runtime_budget_s: int = field(
        default_factory=lambda: int(
            os.getenv("FACTORY_RUNTIME_BUDGET_S", "1800")
        )
    )

    # --- verification pipeline ------------------------------------------
    # Comma separated gates, run in order (blueprint §11).
    verify_gates: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            g.strip()
            for g in os.getenv(
                "FACTORY_VERIFY_GATES", "syntax,test"
            ).split(",")
            if g.strip()
        )
    )

    # --- governance -----------------------------------------------------
    # Worktree isolation seed directory (created per project/task).
    isolation_mode: str = field(
        default_factory=lambda: os.getenv("FACTORY_ISOLATION", "worktree")
    )

    @property
    def db_scheme(self) -> str:
        return self.database_url.split(":", 1)[0]


settings = Settings()
