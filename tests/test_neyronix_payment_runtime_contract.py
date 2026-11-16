"""Runtime wiring contract tests without importing main.py."""
import asyncio
import unittest
from types import SimpleNamespace
from neyrobot_prod import payments

class RuntimeWiringTests(unittest.TestCase):
    def setUp(self):
        self.mod=SimpleNamespace(DB_PATH=":memory:",_yoo_get_payment=lambda _:None,_crypto_get_invoice=lambda _:None)
    def test_patch_installs_all_handlers(self):
        self.assertTrue(payments.patch_runtime(self.mod))
        for name in ("_poll_yoo_credit_payment","_poll_yoo_subscription_payment","_poll_crypto_invoice","_poll_crypto_sub_invoice","on_successful_payment"):
            self.assertTrue(callable(getattr(self.mod,name)))
            self.assertTrue(getattr(getattr(self.mod,name),"_prod_v119_payment",False))
    def test_missing_prerequisite_fails_closed(self):
        self.assertFalse(payments.patch_runtime(SimpleNamespace(DB_PATH=":memory:")))
    def test_precheckout_rejects_invalid_currency(self):
        self.mod._credit_pack_resolve=lambda credits,rub:(1000,990) if (credits,rub)==(1000,990) else None
        answers=[]
        q=SimpleNamespace(invoice_payload="topup:1000:990",currency="USD",total_amount=99000,answer=lambda **kwargs: _record(answers,kwargs))
        asyncio.run(payments.precheckout_handler(self.mod,SimpleNamespace(pre_checkout_query=q),None))
        self.assertFalse(answers[0]["ok"])
    def test_precheckout_accepts_matching_pack(self):
        self.mod._credit_pack_resolve=lambda credits,rub:(1000,990) if (credits,rub)==(1000,990) else None
        answers=[]
        q=SimpleNamespace(invoice_payload="topup:1000:990",currency="RUB",total_amount=99000,answer=lambda **kwargs: _record(answers,kwargs))
        asyncio.run(payments.precheckout_handler(self.mod,SimpleNamespace(pre_checkout_query=q),None))
        self.assertTrue(answers[0]["ok"])
async def _record(answers,kwargs):
    answers.append(kwargs)
if __name__=="__main__":unittest.main()
