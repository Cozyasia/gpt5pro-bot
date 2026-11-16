import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from neyrobot_prod.payments import process_once

class PaymentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"test.db")
        self.mod=SimpleNamespace(DB_PATH=self.path,_credits_to_usd=lambda credits:credits/10)
        self.args=dict(provider="telegram",payment_id="charge-1",provider_charge_id="tg-1",user_id=101,kind="credit_topup",amount=990.0,currency="RUB",metadata={"credits":1000,"amount_rub":990})
    def test_replay_is_idempotent(self):
        self.assertTrue(process_once(self.mod,**self.args).processed)
        self.assertTrue(process_once(self.mod,**self.args).duplicate)
        con=sqlite3.connect(self.path)
        self.assertEqual(con.execute("SELECT usd FROM wallet WHERE user_id=101").fetchone()[0],100.0)
        self.assertEqual(con.execute("SELECT count(*) FROM payment_events").fetchone()[0],1)
        con.close()
    def test_reused_charge_different_user_rejected(self):
        process_once(self.mod,**self.args)
        with self.assertRaisesRegex(ValueError,"conflicting"):
            process_once(self.mod,**(self.args|{"user_id":102}))
    def test_reused_charge_different_amount_rejected(self):
        process_once(self.mod,**self.args)
        with self.assertRaisesRegex(ValueError,"conflicting"):
            process_once(self.mod,**(self.args|{"amount":1990.0}))
    def test_reused_charge_different_metadata_rejected(self):
        process_once(self.mod,**self.args)
        with self.assertRaisesRegex(ValueError,"conflicting"):
            process_once(self.mod,**(self.args|{"metadata":{"credits":3000,"amount_rub":990}}))
    def test_provider_charge_collision_rejected(self):
        process_once(self.mod,**self.args)
        with self.assertRaisesRegex(ValueError,"conflicting"):
            process_once(self.mod,**(self.args|{"payment_id":"different-id","user_id":102}))
if __name__=="__main__": unittest.main()
