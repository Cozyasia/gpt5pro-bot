"""End-to-end isolated SQLite credit ledger smoke test (no provider network calls)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from neyrobot_prod.payments import process_once

class PaymentLedgerSmokeTests(unittest.TestCase):
    def test_credit_topup_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=str(Path(tmp)/"payments.sqlite")
            runtime=SimpleNamespace(DB_PATH=db,_credits_to_usd=lambda credits: credits/10.0)
            args=dict(provider="telegram",payment_id="smoke-payment-1",provider_charge_id="smoke-charge-1",
                      user_id=56789,kind="credit_topup",amount=990.0,currency="RUB",
                      metadata={"credits":1000,"amount_rub":990,"invoice_payload":"topup:1000:990"})
            first=process_once(runtime,**args)
            self.assertTrue(first.applied)
            self.assertFalse(first.duplicate)
            with sqlite3.connect(db) as con:
                balance=con.execute("SELECT usd FROM wallet WHERE user_id=?",(56789,)).fetchone()[0]
                count=con.execute("SELECT count(*) FROM payment_events WHERE provider=? AND payment_id=?",
                                  ("telegram","smoke-payment-1")).fetchone()[0]
            self.assertAlmostEqual(balance,100.0)
            self.assertEqual(count,1)
            second=process_once(runtime,**args)
            self.assertTrue(second.duplicate)
            with sqlite3.connect(db) as con:
                balance2=con.execute("SELECT usd FROM wallet WHERE user_id=?",(56789,)).fetchone()[0]
            self.assertAlmostEqual(balance2,balance)
if __name__=="__main__":unittest.main()
