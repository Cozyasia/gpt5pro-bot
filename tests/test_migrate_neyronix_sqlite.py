import sqlite3

from ops.migrate_neyronix_sqlite import migrate_sqlite


def _create_source(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, usd REAL NOT NULL);
            CREATE TABLE events (kind TEXT NOT NULL, payload TEXT NOT NULL);
            INSERT INTO wallet VALUES (1, 5.0), (2, 7.0);
            INSERT INTO events VALUES ('start', 'a'), ('finish', 'b');
            """
        )


def _create_target(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, usd REAL NOT NULL);
            CREATE TABLE events (kind TEXT NOT NULL, payload TEXT NOT NULL);
            INSERT INTO wallet VALUES (1, 99.0);
            INSERT INTO events VALUES ('start', 'a');
            """
        )


def test_migration_merges_without_overwriting_or_duplicating(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    _create_source(source)
    _create_target(target)

    first = migrate_sqlite(source, target)
    second = migrate_sqlite(source, target)

    assert first["status"] == "applied"
    assert first["inserted"] == {"events": 1, "wallet": 1}
    assert second["status"] == "already_applied"
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT usd FROM wallet WHERE user_id=1").fetchone()[0] == 99.0
        assert conn.execute("SELECT COUNT(*) FROM wallet").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_migration_initializes_missing_target_from_verified_backup(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    _create_source(source)

    result = migrate_sqlite(source, target)

    assert result["status"] == "initialized"
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM wallet").fetchone()[0] == 2
