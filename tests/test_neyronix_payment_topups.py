import sqlite3
import tempfile
import unittest
from pathlib import Path
from neyronix_payment_topups import credit_confirmed_payment

class PaymentTopupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.temp.name)/"test.sqlite")
        with sqlite3.connect(self.db) as con:
            con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL)")
            con.execute("INSERT INTO wallet VALUES (123,0)")
    def tearDown(self): self.temp.cleanup()
    def balance(self):
        with sqlite3.connect(self.db) as con:
            return con.execute("SELECT usd FROM wallet WHERE user_id=123").fetchone()[0]
    def credit(self,**kwargs):
        args=dict(provider="yookassa",payment_id="payment-1",user_id=123,
                  credits=1000,rub=990,credits_per_usd="0.1")
        args.update(kwargs)
        return credit_confirmed_payment(self.db,**args)
    def test_exactly_once(self):
        self.assertEqual(self.credit(),"credited")
        self.assertEqual(self.credit(),"already_credited")
        self.assertEqual(self.balance(),10000)
    def test_mismatched_replay_rejected(self):
        self.credit()
        with self.assertRaises(ValueError): self.credit(credits=3000)
        self.assertEqual(self.balance(),10000)
    def test_provider_scopes_payment_ids(self):
        self.credit()
        self.assertEqual(self.credit(provider="telegram"),"credited")
        self.assertEqual(self.balance(),20000)
    def test_invalid_terms_cannot_credit(self):
        for value in ("NaN",0,-1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.credit(credits_per_usd=value)
        self.assertEqual(self.balance(),0)
    def test_missing_wallet_fails_closed(self):
        with sqlite3.connect(self.db) as con: con.execute("DROP TABLE wallet")
        with self.assertRaises(ValueError): self.credit()
        with sqlite3.connect(self.db) as con:
            self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'neyronix_confirmed_topups\'").fetchone())
if __name__=="__main__": unittest.main()
