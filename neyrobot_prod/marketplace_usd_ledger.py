"""Durable marketplace billing on top of the production USD wallet.

The application stores the unified balance in ``wallet.usd`` and financial
operations in ``credit_ledger``. This adapter follows that contract while
persisting provider and Telegram delivery state for safe restart recovery.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Reservation:
    key: str
    user_id: int
    cents: int
    tx_id: str
    status: str
    newly_reserved: bool


@dataclass(frozen=True)
class StoredOutput:
    index: int
    path: str
    telegram_file_id: str | None
    delivered: bool


@dataclass(frozen=True)
class RecoverableJob:
    key: str
    user_id: int
    cents: int
    tx_id: str
    status: str
    metadata: dict[str, Any]
    outputs: tuple[StoredOutput, ...]


class SQLiteUSDWalletLedger:
    """Atomic USD reservations compatible with the application's wallet."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30)
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def initialize(self) -> None:
        with self._connect() as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(wallet)")}
            if not {"user_id", "usd"}.issubset(columns):
                raise RuntimeError(
                    "Wallet schema mismatch: expected wallet(user_id, usd). "
                    "Paid generation remains disabled."
                )
            con.execute(
                """CREATE TABLE IF NOT EXISTS credit_ledger (
                    tx_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    feature TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    provider_cost_usd REAL NOT NULL,
                    retail_usd REAL NOT NULL,
                    credits REAL NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT,
                    created_ts INTEGER NOT NULL,
                    updated_ts INTEGER NOT NULL
                )"""
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_status "
                "ON credit_ledger(user_id, status, created_ts)"
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS marketplace_jobs (
                    idempotency_key TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    tx_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    provider_operation TEXT,
                    expected_outputs INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    error_text TEXT,
                    created_ts INTEGER NOT NULL,
                    updated_ts INTEGER NOT NULL
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS marketplace_outputs (
                    idempotency_key TEXT NOT NULL,
                    output_index INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    telegram_file_id TEXT,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_ts INTEGER NOT NULL,
                    updated_ts INTEGER NOT NULL,
                    PRIMARY KEY(idempotency_key, output_index),
                    FOREIGN KEY(idempotency_key)
                        REFERENCES marketplace_jobs(idempotency_key)
                )"""
            )

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("USD amount must be positive integer cents")

    @staticmethod
    def _reservation_from_row(row: tuple[Any, ...], *, newly_reserved: bool) -> Reservation:
        return Reservation(
            key=str(row[0]), user_id=int(row[1]), cents=int(row[2]),
            tx_id=str(row[3]), status=str(row[4]), newly_reserved=newly_reserved,
        )

    async def reserve(
        self, *, user_id: int, amount: int, idempotency_key: str,
        provider_cost_usd: float = 0.0, credits: float | None = None,
        expected_outputs: int = 1, metadata: dict[str, Any] | None = None,
    ) -> Reservation | None:
        self._validate_amount(amount)
        if not idempotency_key:
            raise ValueError("Idempotency key required")
        if not isinstance(expected_outputs, int) or expected_outputs <= 0:
            raise ValueError("Expected output count must be a positive integer")
        retail_usd = amount / 100.0
        job_metadata = dict(metadata or {})
        engine = str(job_metadata.get("model") or "gpt-image-2")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT idempotency_key,user_id,amount_cents,tx_id,status "
                "FROM marketplace_jobs WHERE idempotency_key=?", (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if int(existing[1]) != int(user_id) or int(existing[2]) != amount:
                    raise RuntimeError("Idempotency key collision: user or amount mismatch")
                con.commit()
                return self._reservation_from_row(existing, newly_reserved=False)

            con.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),))
            balance_row = con.execute(
                "SELECT COALESCE(usd,0) FROM wallet WHERE user_id=?", (int(user_id),)
            ).fetchone()
            balance = float((balance_row or (0.0,))[0] or 0.0)
            reserved_row = con.execute(
                "SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger "
                "WHERE user_id=? AND status='reserved'", (int(user_id),),
            ).fetchone()
            reserved = float((reserved_row or (0.0,))[0] or 0.0)
            if balance - reserved + 1e-9 < retail_usd:
                con.rollback()
                return None

            now = int(time.time())
            tx_id = uuid.uuid4().hex
            metadata_json = json.dumps(job_metadata, ensure_ascii=False, sort_keys=True)
            con.execute(
                """INSERT INTO credit_ledger(
                    tx_id,user_id,feature,engine,provider_cost_usd,retail_usd,
                    credits,status,metadata_json,created_ts,updated_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (tx_id, int(user_id), "marketplace_cards", engine,
                 float(provider_cost_usd), retail_usd,
                 float(amount if credits is None else credits), "reserved",
                 metadata_json, now, now),
            )
            con.execute(
                """INSERT INTO marketplace_jobs(
                    idempotency_key,user_id,amount_cents,tx_id,status,
                    provider_operation,expected_outputs,metadata_json,error_text,
                    created_ts,updated_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (idempotency_key, int(user_id), amount, tx_id, "reserved",
                 None, expected_outputs, metadata_json, None, now, now),
            )
            con.commit()
            return Reservation(idempotency_key, int(user_id), amount, tx_id, "reserved", True)
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def mark_provider_started(self, reservation: Reservation, *, operation_id: str) -> bool:
        if not operation_id:
            raise ValueError("Provider operation id required")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT user_id,amount_cents,status,provider_operation FROM marketplace_jobs "
                "WHERE idempotency_key=?", (reservation.key,),
            ).fetchone()
            if not row or int(row[0]) != reservation.user_id or int(row[1]) != reservation.cents:
                return False
            if row[2] == "reserved":
                con.execute(
                    "UPDATE marketplace_jobs SET status='provider_started',provider_operation=?,"
                    "updated_ts=? WHERE idempotency_key=?",
                    (operation_id, int(time.time()), reservation.key),
                )
                return True
            return row[2] in {"provider_started", "ready", "delivery_unknown", "delivered"}

    async def record_output(self, reservation: Reservation, *, index: int, path: str) -> bool:
        if not isinstance(index, int) or index < 0 or not path:
            raise ValueError("A non-negative output index and path are required")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT status,expected_outputs FROM marketplace_jobs WHERE idempotency_key=?",
                (reservation.key,),
            ).fetchone()
            if not row or row[0] not in {"provider_started", "ready", "delivery_unknown"}:
                return False
            if index >= int(row[1]):
                raise ValueError("Output index exceeds the quoted output count")
            now = int(time.time())
            con.execute(
                """INSERT INTO marketplace_outputs(
                    idempotency_key,output_index,path,telegram_file_id,delivered,
                    created_ts,updated_ts
                ) VALUES (?,?,?,NULL,0,?,?)
                ON CONFLICT(idempotency_key,output_index) DO UPDATE SET
                    path=excluded.path,updated_ts=excluded.updated_ts""",
                (reservation.key, index, path, now, now),
            )
            count = int(con.execute(
                "SELECT COUNT(*) FROM marketplace_outputs WHERE idempotency_key=?",
                (reservation.key,),
            ).fetchone()[0])
            if count >= int(row[1]):
                con.execute(
                    "UPDATE marketplace_jobs SET status='ready',error_text=NULL,updated_ts=? "
                    "WHERE idempotency_key=?", (now, reservation.key),
                )
            return True

    async def mark_provider_failed(self, reservation: Reservation, *, error: str) -> bool:
        """Release the user's hold after a failed call that produced no artifact."""
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT status,tx_id FROM marketplace_jobs WHERE idempotency_key=?",
                (reservation.key,),
            ).fetchone()
            if not row or row[0] not in {"provider_started", "ready"}:
                con.rollback()
                return False
            now = int(time.time())
            con.execute(
                "UPDATE credit_ledger SET status='released',updated_ts=? "
                "WHERE tx_id=? AND status='reserved'",
                (now, row[1]),
            )
            con.execute(
                "UPDATE marketplace_jobs SET status='failed',error_text=?,updated_ts=? "
                "WHERE idempotency_key=?",
                (str(error)[:1000], now, reservation.key),
            )
            con.commit()
            return True
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def mark_output_delivered(
        self, reservation: Reservation, *, index: int,
        telegram_file_id: str | None = None,
    ) -> bool:
        with self._connect() as con:
            changed = con.execute(
                "UPDATE marketplace_outputs SET delivered=1,telegram_file_id=?,updated_ts=? "
                "WHERE idempotency_key=? AND output_index=?",
                (telegram_file_id, int(time.time()), reservation.key, int(index)),
            )
            return changed.rowcount == 1

    async def mark_delivery_unknown(self, reservation: Reservation, *, error: str) -> bool:
        with self._connect() as con:
            changed = con.execute(
                "UPDATE marketplace_jobs SET status='delivery_unknown',error_text=?,updated_ts=? "
                "WHERE idempotency_key=? AND status IN ('provider_started','ready','delivery_unknown')",
                (str(error)[:1000], int(time.time()), reservation.key),
            )
            return changed.rowcount == 1

    async def commit(self, reservation: Reservation) -> bool:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                """SELECT j.user_id,j.amount_cents,j.status,j.expected_outputs,
                          c.status,c.retail_usd
                   FROM marketplace_jobs j JOIN credit_ledger c ON c.tx_id=j.tx_id
                   WHERE j.idempotency_key=?""", (reservation.key,),
            ).fetchone()
            if not row or int(row[0]) != reservation.user_id or int(row[1]) != reservation.cents:
                con.rollback()
                return False
            if row[2] == "delivered" and row[4] == "charged":
                con.commit()
                return True
            if row[2] not in {"ready", "delivery_unknown"} or row[4] != "reserved":
                con.rollback()
                return False
            delivered = int(con.execute(
                "SELECT COUNT(*) FROM marketplace_outputs "
                "WHERE idempotency_key=? AND delivered=1", (reservation.key,),
            ).fetchone()[0])
            if delivered != int(row[3]):
                con.rollback()
                return False
            retail_usd = float(row[5])
            changed = con.execute(
                "UPDATE wallet SET usd=ROUND(COALESCE(usd,0)-?,2) "
                "WHERE user_id=? AND COALESCE(usd,0)+1e-9>=?",
                (retail_usd, reservation.user_id, retail_usd),
            )
            if changed.rowcount != 1:
                con.rollback()
                return False
            now = int(time.time())
            con.execute(
                "UPDATE credit_ledger SET status='charged',updated_ts=? WHERE tx_id=?",
                (now, reservation.tx_id),
            )
            con.execute(
                "UPDATE marketplace_jobs SET status='delivered',error_text=NULL,updated_ts=? "
                "WHERE idempotency_key=?", (now, reservation.key),
            )
            con.commit()
            return True
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def release(self, reservation: Reservation) -> bool:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT status,provider_operation,tx_id FROM marketplace_jobs "
                "WHERE idempotency_key=?", (reservation.key,),
            ).fetchone()
            if not row or row[0] != "reserved" or row[1]:
                con.rollback()
                return False
            now = int(time.time())
            con.execute(
                "UPDATE credit_ledger SET status='released',updated_ts=? "
                "WHERE tx_id=? AND status='reserved'", (now, row[2]),
            )
            con.execute(
                "UPDATE marketplace_jobs SET status='released',updated_ts=? "
                "WHERE idempotency_key=?", (now, reservation.key),
            )
            con.commit()
            return True
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _load_job(self, con: sqlite3.Connection, row: tuple[Any, ...]) -> RecoverableJob:
        outputs = tuple(
            StoredOutput(int(item[0]), str(item[1]), item[2], bool(item[3]))
            for item in con.execute(
                "SELECT output_index,path,telegram_file_id,delivered "
                "FROM marketplace_outputs WHERE idempotency_key=? ORDER BY output_index",
                (row[0],),
            ).fetchall()
        )
        try:
            metadata = json.loads(row[5] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        return RecoverableJob(
            key=str(row[0]), user_id=int(row[1]), cents=int(row[2]),
            tx_id=str(row[3]), status=str(row[4]),
            metadata=metadata if isinstance(metadata, dict) else {}, outputs=outputs,
        )

    async def status(self, idempotency_key: str) -> RecoverableJob | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT idempotency_key,user_id,amount_cents,tx_id,status,metadata_json "
                "FROM marketplace_jobs WHERE idempotency_key=?", (idempotency_key,),
            ).fetchone()
            return self._load_job(con, row) if row else None

    async def recoverable_jobs(self) -> list[RecoverableJob]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT idempotency_key,user_id,amount_cents,tx_id,status,metadata_json "
                "FROM marketplace_jobs WHERE status IN ('ready','delivery_unknown') "
                "ORDER BY created_ts"
            ).fetchall()
            jobs = [self._load_job(con, row) for row in rows]
        return [job for job in jobs if job.outputs and all(
            Path(output.path).is_file() for output in job.outputs
        )]
