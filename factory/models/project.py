"""Project ORM model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from ..state_machine import ProjectState


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), default=ProjectState.PLANNING.value)
    prd_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_graph_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tasks: Mapped[list["TaskRecord"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ReviewRecord"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project {self.id} {self.state}>"
