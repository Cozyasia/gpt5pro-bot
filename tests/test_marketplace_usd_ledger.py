import asyncio
import os
import sqlite3
import tempfile
import unittest

from neyrobot_prod.marketplace_usd_ledger import SQLiteUSDWalletLedger


class USDLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "wallet.sqlite")
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
            con.execute("INSERT INTO wallet VALUES(42, 10.00)")
        self.ledger = SQLiteUSDWalletLedger(self.path)
        self.ledger.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def balance(self):
        with sqlite3.connect(self.path) as con:
            return con.execute("SELECT usd FROM wallet WHERE user_id=42").fetchone()[0]

    def test_reserve_commit_and_duplicate(self):
        r = asyncio.run(self.ledger.reserve(user_id=42, amount=225, idempotency_key="job-1"))
        self.assertTrue(r.newly_reserved)
        self.assertAlmostEqual(self.balance(), 7.75)
        duplicate = asyncio.run(self.ledger.reserve(user_id=42, amount=225, idempotency_key="job-1"))
        self.assertFalse(duplicate.newly_reserved)
        self.assertAlmostEqual(self.balance(), 7.75)
        asyncio.run(self.ledger.commit(r))
        self.assertAlmostEqual(self.balance(), 7.75)
        with self.assertRaises(RuntimeError):
            asyncio.run(self.ledger.release(r))

    def test_release_refunds_once(self):
        r = asyncio.run(self.ledger.reserve(user_id=42, amount=250, idempotency_key="job-2"))
        asyncio.run(self.ledger.release(r))
        self.assertAlmostEqual(self.balance(), 10.00)
        with self.assertRaises(RuntimeError):
            asyncio.run(self.ledger.release(r))

    def test_insufficient_balance_no_reservation(self):
        r = asyncio.run(self.ledger.reserve(user_id=42, amount=1001, idempotency_key="job-3"))
        self.assertIsNone(r)
        self.assertAlmostEqual(self.balance(), 10.00)

    def test_negative_and_boolean_amounts_rejected(self):
        for amount in (-1, 0, True):
            with self.assertRaises(ValueError):
                asyncio.run(self.ledger.reserve(user_id=42, amount=amount, idempotency_key="invalid"))


if __name__ == "__main__":
    unittest.main()
