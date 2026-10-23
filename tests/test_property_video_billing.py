import sqlite3
import tempfile
import unittest
from pathlib import Path
from property_video_billing import reserve, record_operation, refund_before_submission, mark_delivered, record_result, status

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

if __name__ == "__main__":
    unittest.main()
