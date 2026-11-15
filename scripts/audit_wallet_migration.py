"""Read-only SQLite wallet migration audit for NEYRONIX.

Usage: python scripts/audit_wallet_migration.py /path/to/bot.sqlite3
No rows are modified and no personal user identifiers are printed.
"""
import json
import sqlite3
import sys


def audit(db_path):
    # Open read-only: avoid creating a new database or modifying a live one.
    con = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report = {"wallet_exists": "wallet" in tables, "ledger_exists": "credit_ledger" in tables}
        if "wallet" in tables:
            columns = {row[1] for row in con.execute("PRAGMA table_info(wallet)")}
            report["wallet_columns"] = sorted(columns)
            if "usd" in columns:
                row = con.execute("SELECT COUNT(*), COALESCE(SUM(usd),0), COALESCE(MIN(usd),0), COALESCE(MAX(usd),0) FROM wallet").fetchone()
                report["wallet_count"] = row[0]
                report["legacy_usd_total"] = round(row[1], 4)
                report["legacy_usd_min"] = round(row[2], 4)
                report["legacy_usd_max"] = round(row[3], 4)
        if "credit_ledger" in tables:
            report["ledger_status_counts"] = dict(con.execute("SELECT status, COUNT(*) FROM credit_ledger GROUP BY status").fetchall())
            report["reserved_usd_total"] = round(con.execute("SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger WHERE status='reserved'").fetchone()[0], 4)
        return report
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/audit_wallet_migration.py /path/to/bot.sqlite3")
    print(json.dumps(audit(sys.argv[1]), indent=2, ensure_ascii=False))
