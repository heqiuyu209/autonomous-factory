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
    """Create tables if they don't exist, then apply idempotent schema
    upgrades so a DB created by an earlier build keeps working."""
    from . import models  # noqa: F401  (register models)

    if create_all:
        Base.metadata.create_all(get_engine())
    _ensure_schema(get_engine())


# Tracks columns introduced after the initial schema. A database created by
# an older build lacks them; without an upgrade path a fresh `factory run`
# against such a DB dies with a bare OperationalError. These migrations are
# deliberately inline + idempotent: check existence, then ADD COLUMN.
# Only safe nullable/defaulted additions belong here - no drops, no renames,
# no data rewrites. (V1 ships this as the engineered upgrade path.)
_ADD_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("budget_ledger", "cost_runtime_s", "FLOAT DEFAULT 0"),
    ("budget_accounts", "spent_tokens", "FLOAT DEFAULT 0"),
    ("budget_accounts", "spent_usd", "FLOAT DEFAULT 0"),
)


def _ensure_schema(engine) -> None:
    from sqlalchemy import inspect, text

    _migrate_legacy_budget_ledger(engine)

    inspector = inspect(engine)
    existing = {
        t: {c["name"] for c in inspector.get_columns(t)}
        for t in inspector.get_table_names()
    }
    with engine.begin() as conn:
        for table, column, ddl in _ADD_COLUMNS:
            if table not in existing or column in existing[table]:
                continue
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))


def _migrate_legacy_budget_ledger(engine) -> None:
    """SQLite-only: converge budget_ledger onto the (account_id, ref_type,
    ref_id) unique key.

    The original schema constrained ledger refs globally. A second project
    re-running the same task ref ("T001#1") then hits UNIQUE even though it
    is a different account. SQLite cannot drop a table-level UNIQUE
    constraint, so rebuild the table whenever the legacy autoindex (or no
    correct one) is detected. Idempotent: after the rebuild the correct
    autoindex exists and the migration is a no-op.
    """
    if engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    def _autoindex_cols(conn) -> list[list[str]]:
        rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='budget_ledger' "
                "AND name LIKE 'sqlite_autoindex%'"
            )
        ).fetchall()
        out: list[list[str]] = []
        for (name,) in rows:
            cols = conn.execute(
                text(f'PRAGMA index_info("{name}")')
            ).fetchall()
            out.append([c[2] for c in cols])
        return out

    with engine.connect() as conn:
        if any(
            sorted(cols) == ["account_id", "ref_id", "ref_type"]
            for cols in _autoindex_cols(conn)
        ):
            return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE budget_ledger_new ("
                "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                "account_id VARCHAR(64) NOT NULL, "
                "ref_type VARCHAR(16) NOT NULL, "
                "ref_id VARCHAR(64) NOT NULL, "
                "cost_tokens FLOAT DEFAULT 0, "
                "cost_usd FLOAT DEFAULT 0, "
                "cost_runtime_s FLOAT DEFAULT 0, "
                "agent VARCHAR(64) DEFAULT '', "
                "note TEXT DEFAULT '', "
                "created_at DATETIME, "
                "CONSTRAINT uq_budget_ledger_account_ref "
                "UNIQUE (account_id, ref_type, ref_id), "
                "FOREIGN KEY(account_id) REFERENCES budget_accounts (id) "
                "ON DELETE CASCADE"
                ")"
            )
        )
        # Copy only columns the legacy table actually has; anything missing
        # falls back to the new table's DEFAULT (e.g. cost_runtime_s).
        old_cols = [
            c[1]
            for c in conn.execute(
                text('PRAGMA table_info("budget_ledger")')
            ).fetchall()
        ]
        _LEDGER_COLS = (
            "id",
            "account_id",
            "ref_type",
            "ref_id",
            "cost_tokens",
            "cost_usd",
            "cost_runtime_s",
            "agent",
            "note",
            "created_at",
        )
        copy_cols = [c for c in _LEDGER_COLS if c in old_cols]
        conn.execute(
            text(
                f"INSERT INTO budget_ledger_new ({', '.join(copy_cols)}) "
                f"SELECT {', '.join(copy_cols)} FROM budget_ledger"
            )
        )
        conn.execute(text("DROP TABLE budget_ledger"))
        conn.execute(
            text("ALTER TABLE budget_ledger_new RENAME TO budget_ledger")
        )
        conn.execute(
            text(
                "CREATE INDEX ix_budget_ledger_account_id "
                "ON budget_ledger (account_id)"
            )
        )



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
