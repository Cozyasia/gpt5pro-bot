import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.audit_wallet_migration import audit

class WalletAuditTests(unittest.TestCase):
    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "missing.sqlite"
            with self.assertRaises(sqlite3.OperationalError):
                audit(str(p))
            self.assertFalse(p.exists())

    def test_empty_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "empty.sqlite"
            sqlite3.connect(p).close()
            result = audit(str(p))
            self.assertFalse(result["wallet_exists"])
            self.assertFalse(result["ledger_exists"])

    def test_aggregates_without_user_ids(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "wallet.sqlite"
            with sqlite3.connect(p) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
                con.executemany("INSERT INTO wallet VALUES (?,?)", [(12345,2.5),(98765,3.5)])
                con.execute("CREATE TABLE credit_ledger(tx_id TEXT, status TEXT, retail_usd REAL)")
                con.executemany("INSERT INTO credit_ledger VALUES (?,?,?)", [("a","reserved",1.25),("b","charged",2.0)])
            result = audit(str(p))
            self.assertEqual(result["wallet_count"], 2)
            self.assertEqual(result["legacy_usd_total"], 6)
            self.assertEqual(result["reserved_usd_total"], 1.25)
            self.assertNotIn("12345", str(result))
            self.assertNotIn("98765", str(result))
