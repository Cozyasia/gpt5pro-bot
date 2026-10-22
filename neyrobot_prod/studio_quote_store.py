"""Durable, single-claim Studio quote store.

This module is intentionally independent of Telegram and the wallet. It does
not execute paid actions. Callers must persist the *validated* scene plan as
JSON and must not recompile it after approval.
"""
import json
import os
import sqlite3
import time


class StudioQuoteStore:
    def __init__(self, path):
        self.path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS studio_quotes (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                plan_json TEXT NOT NULL,
                price_credits INTEGER NOT NULL CHECK(price_credits >= 0),
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('pending','cancelled','claimed','expired','completed','failed','needs_review')),
                claimed_at INTEGER,
                updated_at INTEGER NOT NULL
            )""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def create(self, token, user_id, chat_id, plan, price_credits, ttl=600, now=None):
        now = int(time.time() if now is None else now)
        if not 0 < int(ttl) <= 3600:
            raise ValueError("invalid quote ttl")
        serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO studio_quotes
                (token,user_id,chat_id,plan_json,price_credits,created_at,expires_at,state,updated_at)
                VALUES (?,?,?,?,?,?,?,'pending',?)""",
                (token, int(user_id), int(chat_id), serialized, int(price_credits),
                 now, now + int(ttl), now))
            db.commit()

    def decide(self, token, user_id, chat_id, approve, now=None):
        """Atomic one-time decision. Returns approved snapshot or None.

        Claiming is NOT authorization to charge. The caller must separately
        establish an idempotent payment reservation keyed to the quote token.
        """
        now = int(time.time() if now is None else now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT plan_json,price_credits,expires_at,state
                FROM studio_quotes WHERE token=? AND user_id=? AND chat_id=?""",
                (token, int(user_id), int(chat_id))).fetchone()
            if row is None or row[3] != "pending":
                db.rollback()
                return None
            if now >= row[2]:
                db.execute("UPDATE studio_quotes SET state='expired',updated_at=? WHERE token=?",
                           (now, token))
                db.commit()
                return None
            state = "claimed" if approve else "cancelled"
            db.execute("""UPDATE studio_quotes SET state=?,claimed_at=?,updated_at=?
                WHERE token=? AND state='pending'""",
                (state, now if approve else None, now, token))
            db.commit()
            return {"plan": json.loads(row[0]), "price_credits": row[1]} if approve else None

    def mark(self, token, state, now=None):
        """Terminal bookkeeping; never retries a provider call."""
        if state not in ("completed", "failed", "needs_review"):
            raise ValueError("invalid terminal state")
        now = int(time.time() if now is None else now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE studio_quotes SET state=?,updated_at=?
                WHERE token=? AND state='claimed'""", (state, now, token)).rowcount
            db.commit()
            return changed == 1
