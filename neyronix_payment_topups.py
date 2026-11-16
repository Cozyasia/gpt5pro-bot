"""Atomic, idempotent confirmed-payment top-ups for existing USD wallet.

Integration is intentionally opt-in: callers must verify the provider payment
server-side and pass its immutable payment ID. Never call from a raw callback.
"""
from decimal import Decimal
import sqlite3

def credit_confirmed_payment(db_path, *, provider, payment_id, user_id,
                             credits, rub, credits_per_usd):
    if not provider or not payment_id or not str(payment_id).strip():
        raise ValueError("Verified provider and immutable payment ID required")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("Invalid user")
    def decimal(value):
        try:
            d=Decimal(str(value))
            if not d.is_finite(): raise ValueError("Nonfinite amount")
            return d
        except Exception as exc:
            raise ValueError("Invalid amount") from exc
    qty, amount_rub, rate=map(decimal,(credits,rub,credits_per_usd))
    if qty <= 0 or qty != qty.to_integral_value() or amount_rub <= 0 or rate <= 0:
        raise ValueError("Invalid payment terms")
    usd=qty/rate
    # Fail closed: credited USD must not exceed the RUB amount paid, even\n    # under the most conservative possible 1 RUB/USD bound. A verified\n    # settlement conversion is still required before live integration.\n    if usd > amount_rub:\n        raise ValueError("Unsafe top-up conversion: USD credit exceeds RUB payment")\n    # Exact decimal fingerprints, so replays with different terms are rejected.
    fingerprint=(int(user_id),str(qty.normalize()),str(amount_rub.normalize()),str(rate.normalize()))
    con=sqlite3.connect(db_path,timeout=30,isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("BEGIN IMMEDIATE")
        con.execute("""CREATE TABLE IF NOT EXISTS neyronix_confirmed_topups(
            provider TEXT NOT NULL, payment_id TEXT NOT NULL,
            user_id INTEGER NOT NULL, credits TEXT NOT NULL, rub TEXT NOT NULL,
            credits_per_usd TEXT NOT NULL, credited_usd TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(provider,payment_id))""")
        old=con.execute("""SELECT user_id,credits,rub,credits_per_usd
            FROM neyronix_confirmed_topups WHERE provider=? AND payment_id=?""",
            (provider,payment_id)).fetchone()
        if old is not None:
            if tuple(old)!=fingerprint:
                raise ValueError("Payment ID reused with different terms")
            con.commit()
            return "already_credited"
        row=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wallet'").fetchone()
        if row is None:
            raise ValueError("Wallet table missing: refuse to create payment wallet")
        columns={r[1] for r in con.execute("PRAGMA table_info(wallet)")}
        if not {"user_id","usd"}.issubset(columns):
            raise ValueError("Unsupported wallet schema")
        con.execute("INSERT OR IGNORE INTO wallet(user_id,usd) VALUES (?,0)",(user_id,))
        changed=con.execute("UPDATE wallet SET usd=COALESCE(usd,0)+? WHERE user_id=?",(float(usd),user_id)).rowcount
        if changed!=1:
            raise ValueError("Wallet credit failed")
        con.execute("""INSERT INTO neyronix_confirmed_topups(
            provider,payment_id,user_id,credits,rub,credits_per_usd,credited_usd)
            VALUES (?,?,?,?,?,?,?)""",(provider,payment_id,*fingerprint,str(usd)))
        con.commit()
        return "credited"
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
