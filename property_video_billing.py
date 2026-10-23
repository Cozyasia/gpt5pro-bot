"""Atomic, idempotent USD wallet reservations for property-video jobs.

This module is opt-in and does not call a paid video provider.
Requires the existing wallet(user_id, usd) table and its SQLite DB_PATH.
"""
from __future__ import annotations
import sqlite3
from decimal import Decimal, ROUND_UP

def cents(usd):
    value = Decimal(str(usd))
    if not value.is_finite() or value <= 0:
        raise ValueError("Price must be positive")
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_UP))

def _connect(db_path):
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("""CREATE TABLE IF NOT EXISTS property_video_charges (
        job_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL, status TEXT NOT NULL,
        provider_operation TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    return con

def reserve(db_path, job_id, user_id, price_usd):
    """Return reserved/existing/insufficient; charge at most once per job."""
    amount = cents(price_usd)
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            old = con.execute("SELECT user_id,amount_cents,status FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
            if old:
                if old[:2] != (user_id, amount):
                    raise ValueError("Job id reused with different owner or amount")
                con.commit()
                return old[2]
            changed = con.execute(
                "UPDATE wallet SET usd=usd-? WHERE user_id=? AND usd>=?",
                (amount / 100, user_id, amount / 100)
            ).rowcount
            if changed != 1:
                con.rollback()
                return "insufficient"
            con.execute("INSERT INTO property_video_charges(job_id,user_id,amount_cents,status) VALUES(?,?,?,'reserved')",
                        (job_id,user_id,amount))
            con.commit()
            return "reserved"
        except Exception:
            con.rollback()
            raise

def record_operation(db_path, job_id, operation):
    if not operation:
        raise ValueError("Provider operation required")
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT status,provider_operation FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[0] not in ("reserved", "submitted"):
            con.rollback()
            raise ValueError("Job is not reserved")
        if row[1] and row[1] != operation:
            con.rollback()
            raise ValueError("Cannot replace existing provider operation")
        con.execute("UPDATE property_video_charges SET status='submitted',provider_operation=? WHERE job_id=?", (operation,job_id))
        con.commit()

def mark_delivered(db_path, job_id):
    with _connect(db_path) as con:
        con.execute("UPDATE property_video_charges SET status='delivered' WHERE job_id=? AND status='submitted'", (job_id,))

def refund_before_submission(db_path, job_id):
    """Only refundable if no provider operation was recorded. Repeated calls are no-ops."""
    with _connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT user_id,amount_cents,status,provider_operation FROM property_video_charges WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[2] != "reserved" or row[3]:
            con.commit()
            return False
        con.execute("UPDATE wallet SET usd=usd+? WHERE user_id=?", (row[1]/100,row[0]))
        con.execute("UPDATE property_video_charges SET status='refunded' WHERE job_id=?", (job_id,))
        con.commit()
        return True
