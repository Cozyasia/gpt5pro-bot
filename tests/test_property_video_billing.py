import sqlite3
import tempfile
import unittest
from pathlib import Path
from property_video_billing import (
    mark_delivered,
    mark_delivery_unknown,
    record_operation,
    record_result,
    refund_before_submission,
    reserve,
    status,
)

class PropertyVideoBillingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "wallet.db")
        with sqlite3.connect(self.db) as con:
            con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
            con.execute("INSERT INTO wallet VALUES(123, 10.0)")

    def tearDown(self):
        self.tmp.cleanup()

    def balance(self):
        with sqlite3.connect(self.db) as con:
            return con.execute("SELECT usd FROM wallet WHERE user_id=123").fetchone()[0]

    def test_reserve_only_once(self):
        self.assertEqual(reserve(self.db, "job-1", 123, "2.50"), "reserved")
        self.assertEqual(reserve(self.db, "job-1", 123, "2.50"), "reserved")
        # A reserve occupies capacity in credit_ledger; the wallet is charged
        # only after the final MP4 is delivered.
        self.assertAlmostEqual(self.balance(), 10.0)
        record_result(self.db, "job-1", "/tmp/property-review.mp4")
        self.assertTrue(mark_delivered(self.db, "job-1"))
        self.assertAlmostEqual(self.balance(), 7.5)

    def test_insufficient_does_not_debit(self):
        self.assertEqual(reserve(self.db, "job-2", 123, 12), "insufficient")
        self.assertAlmostEqual(self.balance(), 10)

    def test_refund_idempotent(self):
        reserve(self.db, "job-3", 123, 3)
        self.assertTrue(refund_before_submission(self.db, "job-3"))
        self.assertFalse(refund_before_submission(self.db, "job-3"))
        self.assertAlmostEqual(self.balance(), 10)

    def test_submitted_operation_not_refunded(self):
        reserve(self.db, "job-4", 123, 3)
        record_operation(self.db, "job-4", "operations/123")
        self.assertFalse(refund_before_submission(self.db, "job-4"))
        record_result(self.db, "job-4", "/tmp/property-review.mp4")
        mark_delivered(self.db, "job-4")
        self.assertAlmostEqual(self.balance(), 7)

    def test_job_owner_change_rejected(self):
        reserve(self.db, "job-5", 123, 1)
        with self.assertRaises(ValueError):
            reserve(self.db, "job-5", 999, 1)

    def test_owner_bypass_keeps_wallet_and_records_provider_cost(self):
        self.assertEqual(
            reserve(self.db, "owner-job", 123, 0, provider_cost_usd=1.20, owner_bypass=True),
            "reserved",
        )
        record_operation(self.db, "owner-job", "task-owner-1", provider="kling")
        record_result(self.db, "owner-job", "/tmp/property-review.mp4")
        self.assertTrue(mark_delivered(self.db, "owner-job"))
        self.assertAlmostEqual(self.balance(), 10.0)
        with sqlite3.connect(self.db) as con:
            ledger = con.execute(
                "SELECT provider_cost_usd,retail_usd,status FROM credit_ledger WHERE tx_id=(SELECT tx_id FROM property_video_charges WHERE job_id='owner-job')"
            ).fetchone()
        self.assertEqual(ledger, (1.2, 0.0, "owner_delivered"))

    def test_delivery_timeout_keeps_ready_result_recoverable(self):
        reserve(self.db, "delivery-job", 123, 2)
        record_operation(self.db, "delivery-job", "provider-task")
        record_result(self.db, "delivery-job", "/tmp/ready.mp4")
        self.assertTrue(mark_delivery_unknown(self.db, "delivery-job"))
        self.assertEqual(status(self.db, "delivery-job")[0], "delivery_unknown")
        self.assertAlmostEqual(self.balance(), 10.0)
        self.assertTrue(mark_delivered(self.db, "delivery-job", telegram_file_id="file-1"))
        self.assertAlmostEqual(self.balance(), 8.0)

if __name__ == "__main__":
    unittest.main()
