# -*- coding: utf-8 -*-
"""Production SQLite primitives for Neyro-Bot.

This module is dependency-free and safe to import before ``main.py`` finishes
loading. It provides:
- consistent WAL/busy-timeout/foreign-key settings for every connection;
- transactional payment/job/event tables;
- consistent SQLite backups with retention and Medical Card key copies.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_ORIGINAL_CONNECT = sqlite3.connect
_PATCH_LOCK = threading.RLock()
_PATCHED = False
_WAL_READY: set[str] = set()


def _db_path_from_args(database: Any) -> str:
    try:
        return os.fspath(database)
    except Exception:
        return str(database or "")


def _is_file_database(path: str) -> bool:
    low = (path or "").strip().lower()
    return bool(low and low != ":memory:" and "mode=memory" not in low)


def _configure_connection(con: sqlite3.Connection, path: str) -> sqlite3.Connection:
    with con:
        con.execute("PRAGMA busy_timeout=15000")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=NORMAL")
    if _is_file_database(path):
        normalized = os.path.abspath(path) if not path.startswith("file:") else path
        with _PATCH_LOCK:
            if normalized not in _WAL_READY:
                try:
                    con.execute("PRAGMA journal_mode=WAL")
                    _WAL_READY.add(normalized)
                except sqlite3.DatabaseError:
                    pass
    return con


def connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
    """Drop-in replacement for sqlite3.connect with production-safe defaults."""
    kwargs = dict(kwargs)
    kwargs["timeout"] = max(float(kwargs.get("timeout", 0) or 0), 30.0)
    con = _ORIGINAL_CONNECT(database, *args, **kwargs)
    return _configure_connection(con, _db_path_from_args(database))


def install_sqlite_hardening() -> None:
    """Install the connection wrapper once for all modules in the process."""
    global _PATCHED
    with _PATCH_LOCK:
        if _PATCHED:
            return
        if getattr(sqlite3.connect, "_neyrobot_prod_hardened", False):
            _PATCHED = True
            return
        connect._neyrobot_prod_hardened = True  # type: ignore[attr-defined]
        connect._neyrobot_original = _ORIGINAL_CONNECT  # type: ignore[attr-defined]
        sqlite3.connect = connect  # type: ignore[assignment]
        _PATCHED = True


def init_schema(db_path: str) -> None:
    if not db_path:
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS payment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                provider_charge_id TEXT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                metadata_json TEXT,
                error_text TEXT,
                created_ts INTEGER NOT NULL,
                processed_ts INTEGER,
                UNIQUE(provider, payment_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_provider_charge
                ON payment_events(provider, provider_charge_id)
                WHERE provider_charge_id IS NOT NULL AND provider_charge_id <> '';
            CREATE INDEX IF NOT EXISTS idx_payment_user_created
                ON payment_events(user_id, created_ts DESC);

            CREATE TABLE IF NOT EXISTS durable_jobs (
                job_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                feature TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_task_id TEXT,
                state TEXT NOT NULL,
                payload_json TEXT,
                result_url TEXT,
                error_text TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL,
                next_poll_ts INTEGER NOT NULL DEFAULT 0,
                completed_ts INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_durable_jobs_state_poll
                ON durable_jobs(state, next_poll_ts, updated_ts);
            CREATE INDEX IF NOT EXISTS idx_durable_jobs_user
                ON durable_jobs(user_id, updated_ts DESC);

            CREATE TABLE IF NOT EXISTS production_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                user_id INTEGER,
                feature TEXT,
                details_json TEXT,
                created_ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_production_events_created
                ON production_events(created_ts DESC);
            """
        )
        con.commit()
    finally:
        con.close()


def record_event(
    db_path: str,
    event_type: str,
    *,
    severity: str = "info",
    user_id: int | None = None,
    feature: str = "",
    details: Any = None,
) -> None:
    try:
        init_schema(db_path)
        con = connect(db_path)
        try:
            con.execute(
                "INSERT INTO production_events(event_type,severity,user_id,feature,details_json,created_ts) VALUES (?,?,?,?,?,?)",
                (
                    str(event_type or "event")[:80],
                    str(severity or "info")[:20],
                    int(user_id) if user_id else None,
                    str(feature or "")[:100],
                    json.dumps(details, ensure_ascii=False, default=str)[:12000] if details is not None else "",
                    int(time.time()),
                ),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def backup_database(
    db_path: str,
    backup_dir: str,
    *,
    key_paths: tuple[str, ...] = (),
    retention: int = 14,
) -> dict[str, Any]:
    """Create a consistent backup and copy encryption keys beside it."""
    source = Path(db_path)
    target_root = Path(backup_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = target_root / f"subs-{stamp}.sqlite3"
    result: dict[str, Any] = {"ok": False, "db": str(target), "keys": []}

    src = connect(str(source))
    dst = _ORIGINAL_CONNECT(str(target), timeout=30.0)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()

    for raw in key_paths:
        path = Path(raw)
        if not path.exists() or not path.is_file():
            continue
        copied = target_root / f"{stamp}-{path.name}"
        shutil.copy2(path, copied)
        with contextlib_suppress():
            os.chmod(copied, 0o600)
        result["keys"].append(str(copied))

    result["ok"] = target.exists() and target.stat().st_size > 0
    manifest = target_root / f"manifest-{stamp}.json"
    manifest.write_text(json.dumps(result | {"created_ts": int(time.time())}, ensure_ascii=False, indent=2), encoding="utf-8")

    keep = max(2, int(retention or 14))
    backups = sorted(target_root.glob("subs-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        with contextlib_suppress():
            old.unlink()
    manifests = sorted(target_root.glob("manifest-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in manifests[keep:]:
        with contextlib_suppress():
            old.unlink()
    retained_stamps = {p.stem.replace("subs-", "") for p in backups[:keep]}
    for candidate in target_root.iterdir():
        if not candidate.is_file() or candidate.name.startswith(("subs-", "manifest-")):
            continue
        prefix = candidate.name.split("-", 2)
        stamp_prefix = "-".join(prefix[:2]) if len(prefix) >= 2 else ""
        if stamp_prefix and stamp_prefix not in retained_stamps:
            with contextlib_suppress():
                candidate.unlink()

    return result


class contextlib_suppress:
    """Tiny local equivalent to contextlib.suppress to keep import surface small."""

    def __init__(self, *exceptions: type[BaseException]):
        self.exceptions = exceptions or (Exception,)

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return bool(exc_type and issubclass(exc_type, self.exceptions))


__all__ = [
    "connect",
    "install_sqlite_hardening",
    "init_schema",
    "record_event",
    "backup_database",
]
