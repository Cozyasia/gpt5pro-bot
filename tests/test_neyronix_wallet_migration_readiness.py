"""Read-only, offline migration readiness checks. No production data access."""
import ast
import secret_loader
from neyrobot_prod.wallet_migration_audit import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class WalletMigrationReadiness(unittest.TestCase):
    def test_file_activation_is_fail_closed_without_approval(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"DB_PATH": "/data/neyronix-live/subs.db"}, clear=True):
            self.assertFalse(secret_loader._activate_staging_credit_file())
            self.assertNotIn("NEYRONIX_USD_CREDITS_ENABLED", __import__("os").environ)

    def test_migration_is_explicitly_double_gated(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("NEYRONIX_USD_CREDITS_ENABLED", "0")', source)
        self.assertIn('os.environ.get("NEYRONIX_WALLET_MIGRATION_VERIFIED", "0")', source)
        self.assertIn(
            "NEYRONIX_USD_CREDITS_ENABLED = _NEYRONIX_NEW_CREDITS_REQUESTED and _NEYRONIX_WALLET_MIGRATION_VERIFIED",
            source,
        )

    def test_snapshot_audit_reports_aggregates_and_never_marks_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "audit.sqlite")
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
                con.execute("CREATE TABLE payment_events(id INTEGER PRIMARY KEY, status TEXT)")
                con.execute("CREATE TABLE credit_ledger(status TEXT, retail_usd REAL)")
                con.execute("CREATE TABLE subscriptions(until_ts INTEGER)")
                con.execute("CREATE TABLE property_video_charges(job_id TEXT)")
                con.executemany("INSERT INTO wallet VALUES (?,?)", [(11, 10.0), (22, 30.0)])
                con.execute("INSERT INTO payment_events VALUES (1,'processed')")
                con.execute("INSERT INTO credit_ledger VALUES ('reserved',1.4)")
            before = Path(db).read_bytes()
            report = inspect(db)
            self.assertEqual(report["wallet"]["accounts"], 2)
            self.assertEqual(report["wallet"]["total_internal_usd"], 40.0)
            self.assertEqual(report["ledger"]["reserved_usd"], 1.4)
            self.assertEqual(report["payments_by_status"]["processed"], 1)
            self.assertFalse(report["ready_for_migration"])
            self.assertNotIn("11", str(report))
            self.assertEqual(before, Path(db).read_bytes())

    def test_overreserved_wallet_is_flagged_and_backup_is_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "snapshot.sqlite"
            backup = Path(folder) / "backup.sqlite"
            with sqlite3.connect(original) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
                con.execute("CREATE TABLE credit_ledger(user_id INTEGER, status TEXT, retail_usd REAL)")
                con.execute("INSERT INTO wallet VALUES (101,1.0)")
                con.execute("INSERT INTO credit_ledger VALUES (101,'reserved',1.4)")
            with sqlite3.connect(original) as src, sqlite3.connect(backup) as dst:
                src.backup(dst)
            report = inspect(str(backup))
            self.assertEqual(report["reserved_over_balance_accounts"], 1)
            self.assertFalse(report["ready_for_migration"])
            with sqlite3.connect(backup) as con:
                self.assertEqual(con.execute("SELECT usd FROM wallet").fetchone()[0], 1.0)
            self.assertNotIn("101", str(report))

    def test_dry_run_inventory_does_not_change_wallet_or_payments(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "snapshot.sqlite")
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
                con.execute("CREATE TABLE payment_events(id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT)")
                con.executemany("INSERT INTO wallet VALUES (?,?)", [(1, 10.0), (2, 30.0), (3, 70.0)])
                con.executemany("INSERT INTO payment_events VALUES (?,?,?)", [(1, 1, "processed"), (2, 2, "processed")])
                before = (con.execute("SELECT * FROM wallet ORDER BY user_id").fetchall(),
                          con.execute("SELECT * FROM payment_events ORDER BY id").fetchall())
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
                summary = con.execute("SELECT COUNT(*), SUM(usd) FROM wallet").fetchone()
                payments = con.execute("SELECT COUNT(*) FROM payment_events WHERE status='processed'").fetchone()[0]
            self.assertEqual(summary, (3, 110.0))
            self.assertEqual(payments, 2)
            with sqlite3.connect(db) as con:
                after = (con.execute("SELECT * FROM wallet ORDER BY user_id").fetchall(),
                         con.execute("SELECT * FROM payment_events ORDER BY id").fetchall())
            self.assertEqual(before, after)

if __name__ == "__main__":
    unittest.main()
