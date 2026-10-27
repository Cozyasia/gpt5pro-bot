"""Atomic USD reservations against the existing SQLite wallet table.

The caller supplies the production DB path. Reservation amounts are USD cents,
not marketplace 'credits'. Every job has a unique idempotency key.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Reservation:
    key: str
    user_id: int
    cents: int
    newly_reserved: bool


class SQLiteUSDWalletLedger:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def initialize(self):
        with self._connect() as con:
            schema = con.execute("PRAGMA table_info(wallet)").fetchall()
            columns = {row[1] for row in schema}
            if not {'user_id', 'usd'}.issubset(columns):
                raise RuntimeError('Wallet schema mismatch: expected wallet(user_id, usd). Paid generation remains disabled.')
            con.execute("""CREATE TABLE IF NOT EXISTS marketplace_reservations (
                idempotency_key TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('reserved','committed','released'))
            )""")

    async def reserve(self, *, user_id: int, amount: int, idempotency_key: str):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("USD amount must be positive integer cents")
        if not idempotency_key:
            raise ValueError("Idempotency key required")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT user_id, amount_cents FROM marketplace_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                con.rollback()
                if existing != (user_id, amount):
                    raise RuntimeError('Idempotency key collision: user or amount mismatch')
                return Reservation(idempotency_key, existing[0], existing[1], False)
            # The existing wallet stores USD as REAL. Round-trip to cents and
            # update in one SQLite write transaction.
            row = con.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,)).fetchone()
            if row is None or int(round(float(row[0] or 0) * 100)) < amount:
                con.rollback()
                return None
            changed = con.execute(
                "UPDATE wallet SET usd=ROUND(usd - ?, 2) WHERE user_id=? AND usd >= ?",
                (amount / 100, user_id, amount / 100),
            )
            if changed.rowcount != 1:
                con.rollback()
                return None
            con.execute(
                "INSERT INTO marketplace_reservations VALUES (?,?,?,'reserved')",
                (idempotency_key, user_id, amount),
            )
            con.commit()
            return Reservation(idempotency_key, user_id, amount, True)
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def commit(self, reservation: Reservation):
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT status, user_id, amount_cents FROM marketplace_reservations WHERE idempotency_key=?",
                (reservation.key,),
            ).fetchone()
            if row != ('reserved', reservation.user_id, reservation.cents):
                raise RuntimeError("Reservation not eligible for commit")
            con.execute("UPDATE marketplace_reservations SET status='committed' WHERE idempotency_key=?",
                        (reservation.key,))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def release(self, reservation: Reservation):
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT status, user_id, amount_cents FROM marketplace_reservations WHERE idempotency_key=?",
                (reservation.key,),
            ).fetchone()
            if row != ('reserved', reservation.user_id, reservation.cents):
                raise RuntimeError("Reservation not eligible for release")
            con.execute("UPDATE wallet SET usd=ROUND(usd + ?, 2) WHERE user_id=?",
                        (reservation.cents / 100, reservation.user_id))
            con.execute("UPDATE marketplace_reservations SET status='released' WHERE idempotency_key=?",
                        (reservation.key,))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
