"""Durable, idempotent property-video billing on the production wallet ledger."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from decimal import Decimal, ROUND_UP


def cents(usd) -> int:
    value = Decimal(str(usd))
    if not value.is_finite() or value <= 0:
        raise ValueError("Price must be positive")
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_UP))


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("""CREATE TABLE IF NOT EXISTS wallet (
        user_id INTEGER PRIMARY KEY, luma_usd REAL DEFAULT 0.0,
        runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0,
        usd REAL DEFAULT 0.0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS credit_ledger (
        tx_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        feature TEXT NOT NULL, engine TEXT NOT NULL,
        provider_cost_usd REAL NOT NULL, retail_usd REAL NOT NULL,
        credits REAL NOT NULL, status TEXT NOT NULL,
        metadata_json TEXT, created_ts INTEGER NOT NULL,
        updated_ts INTEGER NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS property_video_charges (
        job_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL, status TEXT NOT NULL,
        provider_operation TEXT, tx_id TEXT, result_path TEXT,
        delivered_file_id TEXT, metadata_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS property_video_operations (
        job_id TEXT NOT NULL, scene_index INTEGER NOT NULL,
        provider TEXT NOT NULL, operation_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(job_id, scene_index))""")
    for column, definition in (("tx_id", "TEXT"), ("result_path", "TEXT"),
                               ("delivered_file_id", "TEXT"), ("metadata_json", "TEXT"),
                               ("updated_at", "TEXT")):
        try:
            con.execute(f"ALTER TABLE property_video_charges ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError:
            pass
    return con


def _now() -> int:
    return int(time.time())


def reserve(db_path: str, job_id: str, user_id: int, price_usd, *,
            provider_cost_usd=None, metadata: dict | None = None,
            owner_bypass: bool = False) -> str:
    """Atomically reserve retail balance exactly once for a job.

    ``owner_bypass`` keeps the provider cost and operation in the durable
    ledger for audit/recovery, while reserving zero retail credits. It is
    enabled only by the production owner-test gate in the execution layer.
    """
    amount = 0 if owner_bypass else cents(price_usd)
    retail = amount / 100.0
    provider = float(provider_cost_usd if provider_cost_usd is not None else price_usd)
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        old = con.execute(
            "SELECT user_id,amount_cents,status FROM property_video_charges WHERE job_id=?", (job_id,)
        ).fetchone()
        if old:
            if old[:2] != (int(user_id), amount):
                con.rollback()
                raise ValueError("Job id reused with different owner or amount")
            con.commit()
            return str(old[2])
        if not owner_bypass:
            con.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),))
            balance = float(con.execute("SELECT COALESCE(usd,0) FROM wallet WHERE user_id=?", (int(user_id),)).fetchone()[0])
            reserved = float(con.execute(
                "SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger WHERE user_id=? AND status='reserved'",
                (int(user_id),)).fetchone()[0])
            if balance - reserved + 1e-9 < retail:
                con.rollback()
                return "insufficient"
        tx_id = uuid.uuid4().hex
        now = _now()
        details = dict(metadata or {})
        if owner_bypass:
            details["billing_mode"] = "owner_test"
        metadata_json = json.dumps(details, ensure_ascii=False)
        ledger_status = "owner_reserved" if owner_bypass else "reserved"
        con.execute("""INSERT INTO credit_ledger(
            tx_id,user_id,feature,engine,provider_cost_usd,retail_usd,
            credits,status,metadata_json,created_ts,updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (tx_id, int(user_id), "property_video", "property-video", provider,
             retail, retail, ledger_status, metadata_json, now, now))
        con.execute("""INSERT INTO property_video_charges(
            job_id,user_id,amount_cents,status,tx_id,metadata_json,updated_at)
            VALUES (?,?,?,'reserved',?,?,CURRENT_TIMESTAMP)""",
            (job_id, int(user_id), amount, tx_id, metadata_json))
        con.commit()
        return "reserved"


def record_operation(db_path: str, job_id: str, operation: str, *,
                     provider: str = "unknown", scene_index: int = 0) -> None:
    if not operation:
        raise ValueError("Provider operation required")
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT status FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[0] not in ("reserved", "submitted", "assembling", "ready"):
            con.rollback()
            raise ValueError("Job is not reserved")
        con.execute("""INSERT OR REPLACE INTO property_video_operations(
            job_id,scene_index,provider,operation_id) VALUES(?,?,?,?)""",
            (job_id, int(scene_index), str(provider), str(operation)))
        con.execute("""UPDATE property_video_charges
            SET status='submitted',provider_operation=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
            (str(operation), job_id))
        con.commit()


def record_result(db_path: str, job_id: str, result_path: str) -> bool:
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        changed = con.execute("""UPDATE property_video_charges
            SET status='ready',result_path=?,updated_at=CURRENT_TIMESTAMP
            WHERE job_id=? AND status IN ('reserved','submitted','assembling','ready')""",
            (str(result_path), job_id)).rowcount
        con.commit()
        return changed == 1


def mark_delivered(db_path: str, job_id: str, *, telegram_file_id: str | None = None) -> bool:
    """Charge the reserved retail amount exactly once after Telegram delivery."""
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT user_id,tx_id,status FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            con.rollback()
            return False
        user_id, tx_id, current = row
        if current == "delivered":
            con.commit()
            return True
        if current not in ("ready", "submitted", "assembling") or not tx_id:
            con.rollback()
            return False
        ledger = con.execute("SELECT retail_usd,status FROM credit_ledger WHERE tx_id=?", (tx_id,)).fetchone()
        if not ledger:
            con.rollback()
            return False
        if ledger[1] == "charged":
            con.execute("UPDATE property_video_charges SET status='delivered',delivered_file_id=COALESCE(?,delivered_file_id),updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (telegram_file_id, job_id))
            con.commit()
            return True
        if ledger[1] == "owner_reserved":
            con.execute("UPDATE credit_ledger SET status='owner_delivered',updated_ts=? WHERE tx_id=? AND status='owner_reserved'", (_now(), tx_id))
            con.execute("UPDATE property_video_charges SET status='delivered',delivered_file_id=COALESCE(?,delivered_file_id),updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (telegram_file_id, job_id))
            con.commit()
            return True
        if ledger[1] != "reserved":
            con.rollback()
            return False
        charged = con.execute(
            "UPDATE wallet SET usd=COALESCE(usd,0)-? WHERE user_id=? AND COALESCE(usd,0)+1e-9>=?",
            (float(ledger[0]), int(user_id), float(ledger[0]))).rowcount
        if charged != 1:
            con.rollback()
            return False
        con.execute("UPDATE credit_ledger SET status='charged',updated_ts=? WHERE tx_id=? AND status='reserved'", (_now(), tx_id))
        con.execute("UPDATE property_video_charges SET status='delivered',delivered_file_id=COALESCE(?,delivered_file_id),updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (telegram_file_id, job_id))
        con.commit()
        return True


def refund_before_submission(db_path: str, job_id: str) -> bool:
    """Release only a reservation with no provider operation recorded."""
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT tx_id,status,provider_operation FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[1] != "reserved" or row[2]:
            con.commit()
            return False
        ledger = con.execute("SELECT status FROM credit_ledger WHERE tx_id=?", (row[0],)).fetchone()
        if not ledger or ledger[0] not in ("reserved", "owner_reserved"):
            con.rollback()
            return False
        final_status = "owner_refunded" if ledger[0] == "owner_reserved" else "released"
        con.execute("UPDATE credit_ledger SET status=?,updated_ts=? WHERE tx_id=? AND status=?", (final_status, _now(), row[0], ledger[0]))
        con.execute("UPDATE property_video_charges SET status='refunded',updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        con.commit()
        return True


def status(db_path: str, job_id: str):
    with _connect(db_path) as con:
        return con.execute("""SELECT status,provider_operation,result_path,tx_id,delivered_file_id
            FROM property_video_charges WHERE job_id=?""", (job_id,)).fetchone()


def job_metadata(db_path: str, job_id: str) -> dict:
    with _connect(db_path) as con:
        row = con.execute("SELECT metadata_json FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
    try:
        return json.loads((row or [None])[0] or "{}")
    except (TypeError, ValueError):
        return {}
