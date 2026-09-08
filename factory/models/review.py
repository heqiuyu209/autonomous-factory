"""Review record - every reviewer verdict is persisted for the audit trail."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewRecord(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(16))  # APPROVE | REJECT
    issues: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    project: Mapped["Project"] = relationship(  # noqa: F821
        back_populates="reviews"
    )
    task: Mapped["TaskRecord"] = relationship(  # noqa: F821
        back_populates="reviews"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReviewRecord task={self.task_id} {self.verdict}>"
