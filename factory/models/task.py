"""Task record - one row per task in a project's task graph."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ..state_machine import TaskState


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(String(32), index=True)  # e.g. T010
    title: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), default=TaskState.READY.value)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    acceptance: Mapped[list] = mapped_column(JSON, default=list)
    files: Mapped[list] = mapped_column(JSON, default=list)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    workdir: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped["Project"] = relationship(  # noqa: F821
        back_populates="tasks"
    )
    reviews: Mapped[list["ReviewRecord"]] = relationship(  # noqa: F821
        back_populates="task", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskRecord {self.project_id}:{self.task_id} {self.state}>"
