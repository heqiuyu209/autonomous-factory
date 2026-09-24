"""Schema migration tests (V2 ledger uniqueness fix).

V1's budget_ledger carried a table-level UNIQUE (ref_type, ref_id), which
makes the whole factory single-project: a second account re-running the
same task ref ("T001#1") dies with IntegrityError. The migration rebuilds
the table onto UNIQUE (account_id, ref_type, ref_id) - idempotently.
"""
from __future__ import annotations

import sqlite3

from factory.db import configure_database, init_db, session_scope
from factory.models import BudgetAccount, BudgetLedger


def _make_legacy_db(path, rows=1):
    """Build a DB exactly as V1 created it: old UNIQUE (ref_type, ref_id)."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE budget_accounts (
            id VARCHAR(64) PRIMARY KEY,
            scope VARCHAR(16) NOT NULL,
            limit_tokens FLOAT DEFAULT 0,
            limit_usd FLOAT DEFAULT 0,
            spent_tokens FLOAT DEFAULT 0,
            spent_usd FLOAT DEFAULT 0,
            created_at DATETIME
        );
        CREATE TABLE budget_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id VARCHAR(64) NOT NULL,
            ref_type VARCHAR(16) NOT NULL,
            ref_id VARCHAR(64) NOT NULL,
            cost_tokens FLOAT DEFAULT 0,
            cost_usd FLOAT DEFAULT 0,
            cost_runtime_s FLOAT DEFAULT 0,
            agent VARCHAR(64) DEFAULT '',
            note TEXT DEFAULT '',
            created_at DATETIME,
            CONSTRAINT uq_legacy UNIQUE (ref_type, ref_id),
            FOREIGN KEY(account_id) REFERENCES budget_accounts (id)
        );
        CREATE INDEX ix_budget_ledger_account_id
            ON budget_ledger (account_id);
        """
    )
    con.execute(
        "INSERT INTO budget_accounts (id, scope) VALUES (?, ?)",
        ("project:p_old", "project"),
    )
    for i in range(rows):
        con.execute(
            "INSERT INTO budget_ledger (account_id, ref_type, ref_id,"
            " cost_tokens, agent) VALUES (?, ?, ?, ?, ?)",
            ("project:p_old", "task", f"T001#{i + 1}", 46.0, "coder"),
        )
    con.commit()
    con.close()


def _autoindex_cols(path):
    con = sqlite3.connect(path)
    names = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name='budget_ledger' AND name LIKE 'sqlite_autoindex%'"
        )
    ]
    cols = []
    for n in names:
        cols.append(
            [c[2] for c in con.execute(f'PRAGMA index_info("{n}")')]
        )
    con.close()
    return cols


def test_legacy_ledger_migrates_onto_account_scoped_unique(tmp_path):
    legacy = tmp_path / "legacy.db"
    _make_legacy_db(legacy)
    configure_database(f"sqlite:///{legacy}")
    init_db()

    assert _autoindex_cols(legacy) == [["account_id", "ref_type", "ref_id"]]

    # data survived the rebuild
    with session_scope() as s:
        assert s.query(BudgetLedger).count() == 1
        assert s.query(BudgetLedger).first().account_id == "project:p_old"

    # same task ref under a different account is legal now
    with session_scope() as s:
        s.add(BudgetAccount(id="project:p_new", scope="project"))
        s.add(
            BudgetLedger(
                account_id="project:p_new",
                ref_type="task",
                ref_id="T001#1",
                cost_tokens=1.0,
                agent="coder",
            )
        )
        s.commit()


def test_legacy_ledger_migration_is_idempotent(tmp_path):
    legacy = tmp_path / "legacy.db"
    _make_legacy_db(legacy, rows=2)
    configure_database(f"sqlite:///{legacy}")
    init_db()
    init_db()  # second run must be a no-op

    assert _autoindex_cols(legacy) == [["account_id", "ref_type", "ref_id"]]
    with session_scope() as s:
        assert s.query(BudgetLedger).count() == 2


def test_fresh_db_gets_correct_constraint(tmp_path):
    """A brand-new DB built by init_db already carries the scoped unique
    key and the migration leaves it untouched."""
    db_path = tmp_path / "fresh.db"
    configure_database(f"sqlite:///{db_path}")
    init_db()
    assert _autoindex_cols(db_path) == [["account_id", "ref_type", "ref_id"]]
