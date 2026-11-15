"""Extra transactional invariants using a disposable SQLite database only."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from property_video_billing import reserve, record_operation, record_result, mark_delivered, refund_before_submission, mark_delivery_unknown

class BillingTransactionRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "synthetic.sqlite")
        with sqlite3.connect(self.db) as con:
            con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
            con.execute("INSERT INTO wallet VALUES(1, 10.0)")
    def tearDown(self):
        self.temp.cleanup()
    def balance(self):
        with sqlite3.connect(self.db) as con:
            return con.execute("SELECT usd FROM wallet WHERE user_id=1").fetchone()[0]
    def test_second_reservation_cannot_spend_held_balance(self):
        self.assertEqual(reserve(self.db,"first",1,7), "reserved")
        self.assertEqual(reserve(self.db,"second",1,4), "insufficient")
        self.assertEqual(self.balance(),10)
    def test_delivery_is_idempotent(self):
        self.assertEqual(reserve(self.db,"job",1,3), "reserved")
        self.assertTrue(record_result(self.db,"job","/tmp/synthetic.mp4"))
        self.assertTrue(mark_delivered(self.db,"job",telegram_file_id="file"))
        self.assertTrue(mark_delivered(self.db,"job",telegram_file_id="file"))
        self.assertEqual(self.balance(),7)
    def test_refund_before_provider_submission_releases_hold(self):
        self.assertEqual(reserve(self.db,"job",1,8), "reserved")
        self.assertTrue(refund_before_submission(self.db,"job"))
        self.assertFalse(refund_before_submission(self.db,"job"))
        self.assertEqual(reserve(self.db,"next",1,8), "reserved")
        self.assertEqual(self.balance(),10)
    def test_submitted_provider_job_cannot_be_refunded_early(self):
        reserve(self.db,"job",1,2)
        record_operation(self.db,"job","operation-1",provider="kling")
        self.assertFalse(refund_before_submission(self.db,"job"))
        self.assertEqual(self.balance(),10)
    def test_unknown_delivery_keeps_reservation_until_confirmed(self):
        reserve(self.db,"job",1,4)
        record_result(self.db,"job","/tmp/synthetic.mp4")
        self.assertTrue(mark_delivery_unknown(self.db,"job"))
        self.assertEqual(reserve(self.db,"other",1,7),"insufficient")
        self.assertTrue(mark_delivered(self.db,"job"))
        self.assertEqual(self.balance(),6)

if __name__ == "__main__":
    unittest.main()
