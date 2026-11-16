"""Offline end-to-end Telegram payment integration against disposable SQLite.

No network, provider calls, production database or real funds.
"""
import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from neyrobot_prod.payments import precheckout_handler, successful_payment_handler, process_once

class FakePrecheckout:
    def __init__(self, payload, amount, currency="RUB"):
        self.invoice_payload=payload
        self.total_amount=amount
        self.currency=currency
        self.responses=[]
    async def answer(self, **kwargs):
        self.responses.append(kwargs)

class FakeMessage:
    def __init__(self, payment=None):
        self.successful_payment=payment
        self.replies=[]
    async def reply_text(self, text, **kwargs):
        self.replies.append(text)

class OfflinePaymentIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=str(Path(self.temp.name)/"isolated.sqlite")
        catalog={1000:990,3000:2790,7000:6290}
        self.runtime=SimpleNamespace(
            DB_PATH=self.db,
            CREDIT_PACKAGES_RUB=catalog,
            _credit_pack_resolve=lambda credits,rub: (credits,catalog[credits]) if catalog.get(credits)==rub else None,
            _credits_to_usd=lambda credits: credits/100.0,
        )
    def balance(self):
        with sqlite3.connect(self.db) as con:
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wallet'").fetchone()
            if not exists:
                return 0.0
            row=con.execute("SELECT usd FROM wallet WHERE user_id=123").fetchone()
            return float(row[0]) if row else 0
    def events(self):
        with sqlite3.connect(self.db) as con:
            return con.execute("SELECT COUNT(*) FROM payment_events WHERE status='processed'").fetchone()[0]
    def make_update(self, amount=279000, currency="RUB", payload="topup:3000:2790", charge="charge-1"):
        sp=SimpleNamespace(currency=currency,total_amount=amount,invoice_payload=payload,
                           provider_payment_charge_id=charge,telegram_payment_charge_id="telegram-"+charge)
        message=FakeMessage(sp)
        return SimpleNamespace(effective_user=SimpleNamespace(id=123),message=message,effective_message=message)
    def test_checkout_credit_and_replay(self):
        q=FakePrecheckout("topup:3000:2790",279000)
        asyncio.run(precheckout_handler(self.runtime,SimpleNamespace(pre_checkout_query=q),None))
        self.assertEqual(q.responses,[{"ok":True}])
        update=self.make_update()
        asyncio.run(successful_payment_handler(self.runtime,update,None))
        self.assertAlmostEqual(self.balance(),30.0)
        self.assertEqual(self.events(),1)
        asyncio.run(successful_payment_handler(self.runtime,update,None))
        self.assertAlmostEqual(self.balance(),30.0)
        self.assertEqual(self.events(),1)
    def test_wrong_price_rejected_at_precheckout(self):
        for amount in (249000,279001,0):
            q=FakePrecheckout("topup:3000:2790",amount)
            asyncio.run(precheckout_handler(self.runtime,SimpleNamespace(pre_checkout_query=q),None))
            self.assertFalse(q.responses[0]["ok"])
    def test_wrong_amount_currency_and_package_rejected_after_payment(self):
        for update in (
            self.make_update(amount=249000),
            self.make_update(currency="USD"),
            self.make_update(payload="topup:3000:2490"),
        ):
            with self.assertRaises(ValueError):
                asyncio.run(successful_payment_handler(self.runtime,update,None))
        self.assertEqual(self.balance(),0)
    def test_charge_collision_different_customer_rejected(self):
        asyncio.run(successful_payment_handler(self.runtime,self.make_update(),None))
        with self.assertRaises(ValueError):
            process_once(self.runtime,provider="telegram",payment_id="charge-1",
                         provider_charge_id="charge-1",user_id=999,kind="credit_topup",
                         amount=2790,currency="RUB",metadata={"credits":3000,"amount_rub":2790})
        self.assertAlmostEqual(self.balance(),30.0)
    def test_invalid_topup_does_not_credit(self):
        with self.assertRaises(ValueError):
            process_once(self.runtime,provider="telegram",payment_id="invalid",user_id=123,
                         kind="credit_topup",amount=990,currency="RUB",metadata={"credits":0})
        self.assertEqual(self.balance(),0)
        self.assertEqual(self.events(),0)
if __name__=="__main__":
    unittest.main()
