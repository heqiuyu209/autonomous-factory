"""Portfolio schema (blueprint V6): Portfolio CEO over N products.

The factory stops optimizing a single product. Instead it runs a Darwinian
portfolio (blueprint §18): scout many hypotheses, validate, build, ship,
measure, then **scale winners / experiment with maybes / kill losers**
while re-allocating compute budget dynamically.

    Build / Scale / Kill  (blueprint §1, §18)

The Portfolio CEO never writes code; it decides where agents and budget go
next, feeding the outcome back into Planner -> Coding Agents.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProductSnapshot(BaseModel):
    """One product in the portfolio and the inputs that drove its decision."""

    product_id: str
    name: str = ""
    sources: list[str] = Field(
        default=[],
        description="state files found for this product (validations/deployments/analytics)",
    )
    health: str | None = Field(default=None, description="analytics health if present")


class PortfolioAction(BaseModel):
    product_id: str
    action: Literal["BUILD", "SCALE", "EXPERIMENT", "HOLD", "KILL"]
    priority: int = Field(default=0, ge=0, le=10, description="execution order; higher runs first")
    budget_weight: float = Field(default=0.0, ge=0.0, le=1.0, description="share of compute budget")
    sources: list[str] = []
    reasons: list[str] = []

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json")


class PortfolioReport(BaseModel):
    generated_at: str
    products: list[PortfolioAction]
    summary: str
    allocation: dict[str, float] = Field(default={}, description="product_id -> budget weight")

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json")
