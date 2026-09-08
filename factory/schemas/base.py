"""Shared schema primitives reused across agent contracts."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Evidence(BaseModel):
    """Evidence attached to every decision (blueprint §26 - Judge Score)."""

    kind: str
    detail: str = ""
    value: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Risk(BaseModel):
    severity: Severity = Severity.INFO
    area: str
    description: str
    mitigation: str = ""


class AgentOutput(BaseModel):
    """Universal agent output envelope (blueprint §24 output contract)."""

    status: str = "completed"  # completed | failed | blocked
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)  # file paths produced
    commits: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
