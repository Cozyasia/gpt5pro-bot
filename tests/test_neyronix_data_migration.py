import sqlite3

import pytest

from ops.reconcile_neyronix_db import (
    MigrationConflict,
    backup_sqlite,
    migrate_idempotently,
    reconcile,
)


SCHEMA = """
CREATE TABLE wallet (
    user_id INTEGER PRIMARY KEY,
    luma_usd REAL DEFAULT 0,
    runway_usd REAL DEFAULT 0,
    img_usd REAL DEFAULT 0,
    usd REAL DEFAULT 0
);
CREATE TABLE subscriptions (
    user_id INTEGER PRIMARY KEY,
    until_ts INTEGER NOT NULL,
    tier TEXT
);
CREATE TABLE payment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    payment_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(provider, payment_id)
);
CREATE TABLE ai_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    title TEXT NOT NULL
);
"""


def make_source(path):
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO wallet(user_id,usd) VALUES (?,?)",
            [(101, 12.5), (202, 7.25)],
        )
        con.executemany(
            "INSERT INTO subscriptions VALUES (?,?,?)",
            [(101, 2_000_000_000, "pro"), (202, 2_100_000_000, "start")],
        )
        con.executemany(
            "INSERT INTO payment_events(provider,payment_id,user_id,amount,status) "
            "VALUES (?,?,?,?,?)",
            [
                ("telegram", "pay-a", 101, 990.0, "processed"),
                ("yookassa", "pay-b", 202, 1490.0, "processed"),
            ],
        )
        con.execute(
            "INSERT INTO ai_chats(user_id,telegram_chat_id,title) VALUES (?,?,?)",
            (101, 101, "Рабочий чат"),
        )


def test_consistent_backup_is_integral_and_does_not_overwrite(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    make_source(source)

    evidence = backup_sqlite(source, backup)

    assert evidence["integrity_check"] == "ok"
    assert len(evidence["sha256"]) == 64
    assert evidence["size_bytes"] == backup.stat().st_size
    assert not backup.with_name(backup.name + "-wal").exists()
    assert not backup.with_name(backup.name + "-shm").exists()
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as con:
        assert con.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0] == 2
    with pytest.raises(FileExistsError):
        backup_sqlite(source, backup)


def test_migration_is_repeatable_and_preserves_users_money_and_history(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    make_source(source)

    first = migrate_idempotently(source, target)
    second = migrate_idempotently(source, target)
    report = reconcile(source, target)

    assert first["inserted_rows"] == 7
    assert second["inserted_rows"] == 0
    assert report["ok"] is True
    assert report["tables"]["wallet"]["source_rows"] == 2
    assert report["tables"]["payment_events"]["target_rows"] == 2
    assert report["financial"]["wallet_usd_source"] == 19.75
    assert report["financial"]["wallet_usd_target"] == 19.75
    assert report["financial"]["processed_payments_source"] == 2
    assert report["financial"]["processed_payments_target"] == 2


def test_conflicting_balance_fails_closed_and_rolls_back(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    make_source(source)
    migrate_idempotently(source, target)
    with sqlite3.connect(target) as con:
        con.execute("UPDATE wallet SET usd=999 WHERE user_id=101")
        con.execute("DELETE FROM ai_chats")

    with pytest.raises(MigrationConflict, match="wallet"):
        migrate_idempotently(source, target)

    with sqlite3.connect(target) as con:
        assert con.execute("SELECT usd FROM wallet WHERE user_id=101").fetchone()[0] == 999
        assert con.execute("SELECT COUNT(*) FROM ai_chats").fetchone()[0] == 0


def test_reconciliation_reports_schema_or_row_mismatch_without_user_data(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    make_source(source)
    migrate_idempotently(source, target)
    with sqlite3.connect(target) as con:
        con.execute("DELETE FROM payment_events WHERE payment_id='pay-b'")

    report = reconcile(source, target)

    assert report["ok"] is False
    assert report["tables"]["payment_events"]["source_rows"] == 2
    assert report["tables"]["payment_events"]["target_rows"] == 1
    assert "pay-b" not in str(report)
