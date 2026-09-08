"""Database engine / session bootstrap (SQLAlchemy 2.x).

Supports SQLite (default, zero-setup) and PostgreSQL (prod).
The DB is the durable source of truth, NOT the LLM context (blueprint §21).
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_SessionLocal: sessionmaker | None = None


def _build_engine(url: str):
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        # allow cross-thread use inside orchestrator workers
        kwargs["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return eng


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine(settings.database_url)
    return _engine


def configure_database(url: str) -> None:
    """Re-point the global engine (used by tests/embedders for isolation)."""
    global _engine, _SessionLocal
    _engine = _build_engine(url)
    _SessionLocal = sessionmaker(
        bind=_engine, expire_on_commit=False, class_=Session
    )


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=Session
        )
    return _SessionLocal


def init_db(create_all: bool = True) -> None:
    """Create tables if they don't exist."""
    from . import models  # noqa: F401  (register models)

    if create_all:
        Base.metadata.create_all(get_engine())


def session_scope():
    """Context-manager session; commits on success, rolls back on error."""
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        session = get_sessionmaker()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _scope()


def reset_engine() -> None:
    """For tests: force engine rebuild with a different URL."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
