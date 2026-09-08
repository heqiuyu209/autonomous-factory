"""Schema upgrade path: a DB created by an older build must keep working."""
from __future__ import annotations

import sqlalchemy as sa

from factory.db import _ensure_schema


def _legacy_db(tmp_path, name="legacy.db"):
    """Create a DB matching the pre-upgrade schema (missing the budget
    columns introduced later; see factory/db.py _ADD_COLUMNS)."""
    url = f"sqlite:///{tmp_path}/{name}"
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(
            sa.text(
                "CREATE TABLE budget_ledger ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " account_id VARCHAR(64) NOT NULL,"
                " ref_type VARCHAR(16), ref_id VARCHAR(64),"
                " cost_tokens FLOAT DEFAULT 0, cost_usd FLOAT DEFAULT 0,"
                " agent VARCHAR(64) DEFAULT '', note TEXT DEFAULT '',"
                " created_at DATETIME)"
            )
        )
        c.execute(
            sa.text(
                "CREATE TABLE budget_accounts ("
                " id VARCHAR(64) PRIMARY KEY, scope VARCHAR(16),"
                " limit_tokens FLOAT DEFAULT 0, limit_usd FLOAT DEFAULT 0,"
                " created_at DATETIME)"
            )
        )
    eng.dispose()
    return url


def _cols(eng, table):
    return [c["name"] for c in sa.inspect(eng).get_columns(table)]


def test_legacy_db_gets_missing_columns(tmp_path):
    eng = sa.create_engine(_legacy_db(tmp_path))
    try:
        _ensure_schema(eng)
        assert "cost_runtime_s" in _cols(eng, "budget_ledger")
        assert {"spent_tokens", "spent_usd"} <= set(_cols(eng, "budget_accounts"))
    finally:
        eng.dispose()


def test_ensure_schema_is_idempotent(tmp_path):
    eng = sa.create_engine(_legacy_db(tmp_path))
    try:
        _ensure_schema(eng)
        _ensure_schema(eng)  # second pass must be a no-op (no duplicate/error)
        assert "cost_runtime_s" in _cols(eng, "budget_ledger")
    finally:
        eng.dispose()


def test_ensure_schema_touches_nothing_on_new_db(tmp_path):
    """A freshly created (already current) schema must be left untouched."""
    from factory import models  # noqa: F401  (register tables)
    from factory.db import Base

    url = f"sqlite:///{tmp_path}/new.db"
    eng = sa.create_engine(url)
    try:
        Base.metadata.create_all(eng)
        before = _cols(eng, "budget_ledger")
        _ensure_schema(eng)
        assert _cols(eng, "budget_ledger") == before
    finally:
        eng.dispose()
