#!/usr/bin/env python3
"""Idempotently initialize or merge a verified legacy SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


LEDGER_TABLE = "neyronix_migration_runs"


def _connect(database: str | Path, **kwargs: Any) -> sqlite3.Connection:
    """Bypass the app-wide WAL wrapper for atomic migration files."""
    connector = getattr(sqlite3.connect, "_neyrobot_original", sqlite3.connect)
    return connector(database, **kwargs)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def _create_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_quote(LEDGER_TABLE)} (
            source_sha256 TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            status TEXT NOT NULL,
            inserted_json TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _record(
    conn: sqlite3.Connection,
    source_sha: str,
    source: Path,
    status: str,
    inserted: dict[str, int],
) -> None:
    conn.execute(
        f"INSERT OR IGNORE INTO {_quote(LEDGER_TABLE)} "
        "(source_sha256, source_path, status, inserted_json) VALUES (?, ?, ?, ?)",
        (source_sha, str(source), status, json.dumps(inserted, sort_keys=True)),
    )


def _initialize(source: Path, target: Path, source_sha: str) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".migrating")
    if temporary.exists():
        temporary.unlink()
    with _connect(f"file:{source}?mode=ro", uri=True) as source_conn:
        if _integrity(source_conn) != "ok":
            raise RuntimeError("source database failed integrity_check")
        with _connect(temporary) as target_conn:
            source_conn.backup(target_conn)
            # SQLite backup also copies the source WAL journal mode. Collapse
            # it before the atomic rename so no sidecar is left under the
            # temporary filename.
            target_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            target_conn.execute("PRAGMA journal_mode=DELETE")
            _create_ledger(target_conn)
            _record(target_conn, source_sha, source, "initialized", {})
            if _integrity(target_conn) != "ok":
                raise RuntimeError("initialized database failed integrity_check")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return {"status": "initialized", "source_sha256": source_sha, "inserted": {}}


def _table_names(conn: sqlite3.Connection, schema: str) -> list[str]:
    rows = conn.execute(
        f"SELECT name FROM {_quote(schema)}.sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [str(row[0]) for row in rows if row[0] != LEDGER_TABLE]


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [
        str(row[1])
        for row in conn.execute(
            f"PRAGMA {_quote(schema)}.table_info({_quote(table)})"
        )
    ]


def _merge(source: Path, target: Path, source_sha: str) -> dict[str, Any]:
    inserted: dict[str, int] = {}
    with _connect(target, uri=True) as conn:
        if _integrity(conn) != "ok":
            raise RuntimeError("target database failed integrity_check")
        _create_ledger(conn)
        previous = conn.execute(
            f"SELECT status FROM {_quote(LEDGER_TABLE)} WHERE source_sha256=?",
            (source_sha,),
        ).fetchone()
        if previous:
            return {
                "status": "already_applied",
                "source_sha256": source_sha,
                "inserted": {},
            }

        conn.execute("ATTACH DATABASE ? AS legacy", (f"file:{source}?mode=ro",))
        try:
            if str(conn.execute("PRAGMA legacy.integrity_check").fetchone()[0]) != "ok":
                raise RuntimeError("source database failed integrity_check")
            target_tables = set(_table_names(conn, "main"))
            conn.execute("BEGIN IMMEDIATE")
            for table in _table_names(conn, "legacy"):
                if table not in target_tables:
                    create_sql = conn.execute(
                        "SELECT sql FROM legacy.sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()[0]
                    conn.execute(str(create_sql))
                    target_tables.add(table)

                source_columns = _columns(conn, "legacy", table)
                target_columns = set(_columns(conn, "main", table))
                missing = [column for column in source_columns if column not in target_columns]
                if missing:
                    raise RuntimeError(f"target table {table} is missing columns: {missing}")
                if not source_columns:
                    continue

                table_q = _quote(table)
                columns_q = ", ".join(_quote(column) for column in source_columns)
                select_q = ", ".join(f"s.{_quote(column)}" for column in source_columns)
                equality = " AND ".join(
                    f"t.{_quote(column)} IS s.{_quote(column)}"
                    for column in source_columns
                )
                before = conn.total_changes
                conn.execute(
                    f"INSERT OR IGNORE INTO main.{table_q} ({columns_q}) "
                    f"SELECT {select_q} FROM legacy.{table_q} AS s "
                    f"WHERE NOT EXISTS (SELECT 1 FROM main.{table_q} AS t WHERE {equality})"
                )
                inserted[table] = conn.total_changes - before

            _record(conn, source_sha, source, "applied", inserted)
            conn.commit()
            if _integrity(conn) != "ok":
                raise RuntimeError("merged database failed integrity_check")
        finally:
            conn.execute("DETACH DATABASE legacy")
    return {"status": "applied", "source_sha256": source_sha, "inserted": inserted}


def migrate_sqlite(source: str | Path, target: str | Path) -> dict[str, Any]:
    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_sha = _sha256(source_path)
    if not target_path.exists() or target_path.stat().st_size == 0:
        return _initialize(source_path, target_path, source_sha)
    return _merge(source_path, target_path, source_sha)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    print(json.dumps(migrate_sqlite(args.source, args.target), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
