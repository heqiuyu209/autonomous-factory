"""Unified Agent Protocol (blueprint §24).

Every agent in the factory speaks the same wire format -
structured input + structured output, never free-form chatter.
"""
from __future__ import annotations

__all__ = ["AgentOutput", "Evidence", "Risk"]

from .base import AgentOutput, Evidence, Risk
