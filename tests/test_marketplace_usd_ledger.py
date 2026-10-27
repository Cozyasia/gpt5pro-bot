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
            con.execute(
                "CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, "
                "luma_usd REAL DEFAULT 0, runway_usd REAL DEFAULT 0, "
                "img_usd REAL DEFAULT 0, usd REAL DEFAULT 0)"
            )
            con.execute("INSERT INTO wallet(user_id, usd) VALUES(42, 10.00)")
        self.ledger = SQLiteUSDWalletLedger(self.path)
        self.ledger.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def balance(self):
        with sqlite3.connect(self.path) as con:
            return con.execute("SELECT usd FROM wallet WHERE user_id=42").fetchone()[0]

    def reserve(self, key="job-1", cents=225, outputs=1):
        return asyncio.run(self.ledger.reserve(
            user_id=42,
            amount=cents,
            idempotency_key=key,
            provider_cost_usd=1.10,
            credits=cents,
            expected_outputs=outputs,
            metadata={"model": "gpt-image-2"},
        ))

    def deliver(self, reservation, outputs=1):
        asyncio.run(self.ledger.mark_provider_started(reservation, operation_id="openai-started"))
        for index in range(outputs):
            asyncio.run(self.ledger.record_output(reservation, index=index, path=f"/tmp/{index}.png"))
            asyncio.run(self.ledger.mark_output_delivered(
                reservation, index=index, telegram_file_id=f"telegram-{index}"
            ))

    def test_reserve_uses_existing_ledger_capacity_without_early_wallet_debit(self):
        reservation = self.reserve()
        duplicate = self.reserve()
        self.assertTrue(reservation.newly_reserved)
        self.assertFalse(duplicate.newly_reserved)
        self.assertEqual(duplicate.status, "reserved")
        self.assertAlmostEqual(self.balance(), 10.00)
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT feature,engine,retail_usd,credits,status FROM credit_ledger WHERE tx_id=?",
                (reservation.tx_id,),
            ).fetchone()
        self.assertEqual(row, ("marketplace_cards", "gpt-image-2", 2.25, 225.0, "reserved"))

    def test_commit_debits_once_only_after_all_outputs_are_delivered(self):
        reservation = self.reserve(outputs=2)
        self.deliver(reservation, outputs=2)
        self.assertTrue(asyncio.run(self.ledger.commit(reservation)))
        self.assertAlmostEqual(self.balance(), 7.75)
        self.assertTrue(asyncio.run(self.ledger.commit(reservation)))
        self.assertAlmostEqual(self.balance(), 7.75)
        self.assertEqual(asyncio.run(self.ledger.status(reservation.key)).status, "delivered")

    def test_commit_preserves_existing_subcent_wallet_precision(self):
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE wallet SET usd=10.005 WHERE user_id=42")
        reservation = self.reserve(key="precision")
        self.deliver(reservation)
        self.assertTrue(asyncio.run(self.ledger.commit(reservation)))
        self.assertAlmostEqual(self.balance(), 7.755, places=6)

    def test_commit_refuses_partial_delivery_without_debit(self):
        reservation = self.reserve(outputs=2)
        asyncio.run(self.ledger.mark_provider_started(reservation, operation_id="started"))
        asyncio.run(self.ledger.record_output(reservation, index=0, path="/tmp/0.png"))
        asyncio.run(self.ledger.mark_output_delivered(
            reservation, index=0, telegram_file_id="telegram-0"
        ))
        self.assertFalse(asyncio.run(self.ledger.commit(reservation)))
        self.assertAlmostEqual(self.balance(), 10.00)

    def test_release_is_allowed_only_before_provider_start(self):
        before = self.reserve(key="before")
        self.assertTrue(asyncio.run(self.ledger.release(before)))
        self.assertFalse(asyncio.run(self.ledger.release(before)))
        after = self.reserve(key="after")
        asyncio.run(self.ledger.mark_provider_started(after, operation_id="started"))
        self.assertFalse(asyncio.run(self.ledger.release(after)))
        self.assertAlmostEqual(self.balance(), 10.00)

    def test_provider_failure_releases_hold_without_debit_when_no_output_exists(self):
        reservation = self.reserve(key="provider-failed")
        asyncio.run(self.ledger.mark_provider_started(reservation, operation_id="started"))
        self.assertTrue(asyncio.run(self.ledger.mark_provider_failed(
            reservation, error="provider returned no image"
        )))
        self.assertAlmostEqual(self.balance(), 10.00)
        self.assertEqual(asyncio.run(self.ledger.status(reservation.key)).status, "failed")

    def test_reservation_capacity_prevents_oversubscription(self):
        self.reserve(key="first", cents=1000)
        second = self.reserve(key="second", cents=1)
        self.assertIsNone(second)
        self.assertAlmostEqual(self.balance(), 10.00)

    def test_idempotency_collision_is_rejected(self):
        self.reserve(key="same", cents=200)
        with self.assertRaisesRegex(RuntimeError, "collision"):
            self.reserve(key="same", cents=300)

    def test_invalid_wallet_schema_fails_closed(self):
        with sqlite3.connect(self.path) as con:
            con.execute("DROP TABLE wallet")
            con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, balance REAL)")
        with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
            self.ledger.initialize()

    def test_invalid_amounts_are_rejected(self):
        for amount in (-1, 0, True):
            with self.assertRaises(ValueError):
                self.reserve(key=f"invalid-{amount}", cents=amount)


if __name__ == "__main__":
    unittest.main()
