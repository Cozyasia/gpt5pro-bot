#!/usr/bin/env python3
"""Fail-closed SQLite backup, migration rehearsal and reconciliation.

The tool never invents credits or merges conflicting financial records.  It
copies rows by their declared primary keys, verifies every existing row byte
for byte, and rolls the whole target transaction back on any conflict.
Reports contain aggregate counts only; they never contain Telegram user IDs,
payment IDs, chat text, file identifiers, or other user data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable


# sitecustomize deliberately hardens application connections into WAL mode.
# Backup artifacts must instead be self-contained single files, so operations
# here use the original sqlite3 connector retained by the hardening layer.
_RAW_CONNECT = getattr(sqlite3.connect, "_neyrobot_original", sqlite3.connect)


class MigrationConflict(RuntimeError):
    """Raised when an existing target row or schema differs from the source."""


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _connect_readonly(path: Path) -> sqlite3.Connection:
    con = _RAW_CONNECT(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _integrity(con: sqlite3.Connection) -> str:
    row = con.execute("PRAGMA integrity_check").fetchone()
    return str((row or ("missing",))[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite(source: str | Path, target: str | Path) -> dict[str, Any]:
    """Create a consistent online backup without overwriting an existing file."""
    source_path, target_path = _path(source), _path(target)
    if source_path == target_path:
        raise ValueError("source and target must be different files")
    if not source_path.is_file() or source_path.stat().st_size <= 0:
        raise FileNotFoundError("source database is missing or empty")
    if target_path.exists():
        raise FileExistsError(str(target_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _connect_readonly(source_path) as src:
            if _integrity(src) != "ok":
                raise MigrationConflict("source database integrity check failed")
            with _RAW_CONNECT(target_path, timeout=30) as dst:
                src.backup(dst, pages=128, sleep=0.2)
                dst.commit()
                dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                dst.execute("PRAGMA journal_mode=DELETE").fetchone()
        with _connect_readonly(target_path) as check:
            integrity = _integrity(check)
        if integrity != "ok":
            raise MigrationConflict("backup integrity check failed")
        target_path.chmod(0o600)
        return {
            "integrity_check": integrity,
            "size_bytes": target_path.stat().st_size,
            "sha256": _sha256(target_path),
        }
    except Exception:
        target_path.unlink(missing_ok=True)
        raise


def _schema_objects(con: sqlite3.Connection, object_type: str) -> list[tuple[str, str]]:
    return [
        (str(name), str(sql))
        for name, sql in con.execute(
            "SELECT name,sql FROM sqlite_master "
            "WHERE type=? AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
            "ORDER BY name",
            (object_type,),
        )
    ]


def _columns(con: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    return list(con.execute(f"PRAGMA table_info({_quote(table)})"))


def _primary_key(columns: Iterable[tuple[Any, ...]], table: str) -> list[str]:
    ordered = sorted(
        ((int(row[5]), str(row[1])) for row in columns if int(row[5]) > 0),
        key=lambda item: item[0],
    )
    if not ordered:
        raise MigrationConflict(f"table {table} has no declared primary key")
    return [name for _position, name in ordered]


def _existing_object_names(con: sqlite3.Connection, object_type: str) -> set[str]:
    return {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type=?", (object_type,))
    }


def migrate_idempotently(source: str | Path, target: str | Path) -> dict[str, Any]:
    """Copy an offline source into a target, rolling back on any difference.

    Re-running against an unchanged source and target inserts zero rows.  A
    target value is never overwritten, which makes balance/payment conflicts a
    hard gate instead of silently choosing one side.
    """
    source_path, target_path = _path(source), _path(target)
    if source_path == target_path:
        raise ValueError("source and target must be different files")
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)

    inserted = 0
    with _connect_readonly(source_path) as src:
        if _integrity(src) != "ok":
            raise MigrationConflict("source database integrity check failed")
        tables = _schema_objects(src, "table")
        with _RAW_CONNECT(target_path, timeout=30) as dst:
            dst.execute("PRAGMA busy_timeout=30000")
            dst.execute("PRAGMA foreign_keys=OFF")
            try:
                dst.execute("BEGIN IMMEDIATE")
                existing_tables = _existing_object_names(dst, "table")
                for table, create_sql in tables:
                    if table not in existing_tables:
                        dst.execute(create_sql)
                        existing_tables.add(table)

                    source_columns = _columns(src, table)
                    target_columns = _columns(dst, table)
                    source_names = [str(row[1]) for row in source_columns]
                    target_names = [str(row[1]) for row in target_columns]
                    if source_names != target_names:
                        raise MigrationConflict(f"schema conflict in table {table}")
                    key_names = _primary_key(source_columns, table)
                    key_indexes = [source_names.index(name) for name in key_names]
                    select_sql = f"SELECT {','.join(map(_quote, source_names))} FROM {_quote(table)}"
                    insert_sql = (
                        f"INSERT INTO {_quote(table)} ({','.join(map(_quote, source_names))}) "
                        f"VALUES ({','.join('?' for _ in source_names)})"
                    )
                    where = " AND ".join(f"{_quote(name)} IS ?" for name in key_names)
                    target_sql = (
                        f"SELECT {','.join(map(_quote, target_names))} "
                        f"FROM {_quote(table)} WHERE {where}"
                    )
                    for source_row in src.execute(select_sql):
                        key = tuple(source_row[index] for index in key_indexes)
                        target_row = dst.execute(target_sql, key).fetchone()
                        if target_row is not None:
                            if tuple(target_row) != tuple(source_row):
                                raise MigrationConflict(f"row conflict in table {table}")
                            continue
                        try:
                            dst.execute(insert_sql, tuple(source_row))
                        except sqlite3.IntegrityError as exc:
                            raise MigrationConflict(f"unique conflict in table {table}") from exc
                        inserted += 1

                for object_type in ("index", "trigger", "view"):
                    existing = _existing_object_names(dst, object_type)
                    for name, sql in _schema_objects(src, object_type):
                        if name not in existing:
                            dst.execute(sql)
                            existing.add(name)

                foreign_key_errors = list(dst.execute("PRAGMA foreign_key_check"))
                if foreign_key_errors:
                    raise MigrationConflict("target foreign key check failed")
                dst.commit()
                dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                dst.execute("PRAGMA journal_mode=DELETE").fetchone()
            except Exception:
                dst.rollback()
                raise

    with _connect_readonly(target_path) as check:
        integrity = _integrity(check)
    if integrity != "ok":
        raise MigrationConflict("target database integrity check failed")
    return {
        "inserted_rows": inserted,
        "tables": len(tables),
        "integrity_check": integrity,
    }


def _row_digest(con: sqlite3.Connection, table: str, columns: list[str], keys: list[str]) -> str:
    digest = hashlib.sha256()
    sql = (
        f"SELECT {','.join(map(_quote, columns))} FROM {_quote(table)} "
        f"ORDER BY {','.join(map(_quote, keys))}"
    )
    for row in con.execute(sql):
        for value in row:
            if isinstance(value, bytes):
                raw = b"b:" + value
            else:
                raw = (type(value).__name__ + ":" + repr(value)).encode("utf-8")
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    return digest.hexdigest()


def _scalar(con: sqlite3.Connection, sql: str) -> float | int:
    row = con.execute(sql).fetchone()
    return (row or (0,))[0] or 0


def reconcile(source: str | Path, target: str | Path) -> dict[str, Any]:
    """Return an aggregate, PII-free equality and financial reconciliation."""
    source_path, target_path = _path(source), _path(target)
    with _connect_readonly(source_path) as src, _connect_readonly(target_path) as dst:
        source_integrity, target_integrity = _integrity(src), _integrity(dst)
        source_tables = dict(_schema_objects(src, "table"))
        target_tables = dict(_schema_objects(dst, "table"))
        table_report: dict[str, dict[str, Any]] = {}
        all_ok = source_integrity == target_integrity == "ok"
        for table in sorted(set(source_tables) | set(target_tables)):
            source_rows = int(_scalar(src, f"SELECT COUNT(*) FROM {_quote(table)}")) if table in source_tables else 0
            target_rows = int(_scalar(dst, f"SELECT COUNT(*) FROM {_quote(table)}")) if table in target_tables else 0
            schema_match = source_tables.get(table) == target_tables.get(table)
            content_match = False
            if schema_match:
                cols_info = _columns(src, table)
                names = [str(row[1]) for row in cols_info]
                keys = _primary_key(cols_info, table)
                content_match = _row_digest(src, table, names, keys) == _row_digest(dst, table, names, keys)
            table_report[table] = {
                "source_rows": source_rows,
                "target_rows": target_rows,
                "schema_match": schema_match,
                "content_match": content_match,
            }
            all_ok = all_ok and schema_match and content_match

        financial: dict[str, float | int] = {}
        if "wallet" in source_tables and "wallet" in target_tables:
            financial.update(
                wallet_usd_source=round(float(_scalar(src, "SELECT COALESCE(SUM(usd),0) FROM wallet")), 8),
                wallet_usd_target=round(float(_scalar(dst, "SELECT COALESCE(SUM(usd),0) FROM wallet")), 8),
            )
        if "payment_events" in source_tables and "payment_events" in target_tables:
            financial.update(
                processed_payments_source=int(_scalar(src, "SELECT COUNT(*) FROM payment_events WHERE status='processed'")),
                processed_payments_target=int(_scalar(dst, "SELECT COUNT(*) FROM payment_events WHERE status='processed'")),
            )
        if financial:
            pairs = list(financial.items())
            for index in range(0, len(pairs), 2):
                all_ok = all_ok and pairs[index][1] == pairs[index + 1][1]

        return {
            "ok": bool(all_ok),
            "source_integrity": source_integrity,
            "target_integrity": target_integrity,
            "tables": table_report,
            "financial": financial,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("source")
    backup.add_argument("target")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("source")
    migrate.add_argument("target")
    compare = sub.add_parser("reconcile")
    compare.add_argument("source")
    compare.add_argument("target")
    args = parser.parse_args()
    if args.command == "backup":
        result = backup_sqlite(args.source, args.target)
    elif args.command == "migrate":
        result = migrate_idempotently(args.source, args.target)
    else:
        result = reconcile(args.source, args.target)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
