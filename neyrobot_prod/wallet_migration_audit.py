"""Read-only SQLite wallet migration inventory. No credentials or production access.

Usage: python -m neyrobot_prod.wallet_migration_audit /path/to/snapshot.sqlite
Prints aggregate JSON only; never outputs user IDs or payment identifiers.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path

TABLES = ("wallet", "payment_events", "subscriptions", "credit_ledger", "property_video_charges")

def inspect(db_path: str) -> dict:
    path = Path(db_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Expected a SQLite file")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {"schema": "neyronix-wallet-audit-v1", "tables": {}, "warnings": [], "ready_for_migration": False}
        for table in TABLES:
            if table not in tables:
                result["tables"][table] = {"present": False}
                result["warnings"].append(f"Missing table: {table}")
                continue
            columns = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            result["tables"][table] = {"present": True, "rows": con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]}
            if table == "wallet":
                if "usd" not in columns:
                    result["warnings"].append("wallet.usd missing")
                else:
                    count, total, negatives, nulls = con.execute(
                        "SELECT COUNT(*),COALESCE(SUM(usd),0),"
                        "SUM(CASE WHEN usd<0 THEN 1 ELSE 0 END),"
                        "SUM(CASE WHEN usd IS NULL THEN 1 ELSE 0 END) FROM wallet"
                    ).fetchone()
                    result["wallet"] = {"accounts": count, "total_internal_usd": round(total, 6),
                                        "negative_accounts": negatives or 0, "null_balances": nulls or 0}
                    if negatives or nulls:
                        result["warnings"].append("Invalid wallet balances detected")
            if table == "credit_ledger" and {"status", "retail_usd"}.issubset(columns):
                result["ledger"] = {
                    "reserved_usd": round(con.execute("SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger WHERE status='reserved'").fetchone()[0], 6),
                    "reserved_jobs": con.execute("SELECT COUNT(*) FROM credit_ledger WHERE status='reserved'").fetchone()[0],
                }
                if result["ledger"]["reserved_jobs"]:
                    result["warnings"].append("Outstanding reservations require reconciliation")
            if table == "payment_events" and "status" in columns:
                result["payments_by_status"] = dict(con.execute(
                    "SELECT status,COUNT(*) FROM payment_events GROUP BY status").fetchall())
            if table == "subscriptions" and "until_ts" in columns:
                result["subscriptions"] = {"active": con.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE until_ts>CAST(strftime('%s','now') AS INTEGER)").fetchone()[0]}
        if "wallet" in tables and "credit_ledger" in tables:
            wallet_columns = {r[1] for r in con.execute("PRAGMA table_info(wallet)")}
            ledger_columns = {r[1] for r in con.execute("PRAGMA table_info(credit_ledger)")}
            if {"user_id", "usd"}.issubset(wallet_columns) and {"user_id", "retail_usd", "status"}.issubset(ledger_columns):
                overdrawn = con.execute(
                    "SELECT COUNT(*) FROM ("
                    "SELECT w.user_id FROM wallet w "
                    "LEFT JOIN credit_ledger l ON l.user_id=w.user_id AND l.status='reserved' "
                    "GROUP BY w.user_id HAVING COALESCE(w.usd,0)+0.000001 < COALESCE(SUM(l.retail_usd),0))"
                ).fetchone()[0]
                result["reserved_over_balance_accounts"] = overdrawn
                if overdrawn:
                    result["warnings"].append("Reservations exceed wallet balance for some accounts")
        result["warnings"].append("Legacy credit valuation and top-up history require explicit business reconciliation")
        return result
    finally:
        con.close()

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="Consistent, offline SQLite snapshot (not live database)")
    args = parser.parse_args()
    print(json.dumps(inspect(args.snapshot), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
