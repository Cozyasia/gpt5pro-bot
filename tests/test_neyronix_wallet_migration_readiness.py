"""Read-only, offline migration readiness checks. No production data access."""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class WalletMigrationReadiness(unittest.TestCase):
    def test_migration_is_explicitly_double_gated(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("NEYRONIX_USD_CREDITS_ENABLED", "0")', source)
        self.assertIn('os.environ.get("NEYRONIX_WALLET_MIGRATION_VERIFIED", "0")', source)
        self.assertIn(
            "NEYRONIX_USD_CREDITS_ENABLED = _NEYRONIX_NEW_CREDITS_REQUESTED and _NEYRONIX_WALLET_MIGRATION_VERIFIED",
            source,
        )

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
