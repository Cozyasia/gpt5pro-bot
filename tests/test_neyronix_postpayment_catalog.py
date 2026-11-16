"""Verify Telegram successful-payment catalog validation is fail-closed."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from neyrobot_prod import payments

class CatalogGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mod=SimpleNamespace(DB_PATH=str(Path(self.temp.name)/"billing.sqlite"),
            _credit_pack_resolve=lambda credits,rub:(1000,990) if (credits,rub)==(1000,990) else None,
            SUBS_TIERS={"pro":{"rub":1990}})
    def _update(self,payload,amount):
        sp=SimpleNamespace(currency="RUB",total_amount=amount,invoice_payload=payload,
            provider_payment_charge_id="test-provider-charge",telegram_payment_charge_id="test-tg-charge")
        return SimpleNamespace(message=SimpleNamespace(successful_payment=sp),
            effective_user=SimpleNamespace(id=98765),
            effective_message=SimpleNamespace(reply_text=self._reply))
    async def _reply(self,text):
        pass
    def test_subscription_amount_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(payments.successful_payment_handler(self.mod,self._update("sub:pro:1",100),None))
    def test_topup_amount_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(payments.successful_payment_handler(self.mod,self._update("topup:1000:990",100),None))
    def test_unknown_payload_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(payments.successful_payment_handler(self.mod,self._update("unknown",99000),None))
    def test_missing_catalog_rejected(self):
        del self.mod._credit_pack_resolve
        with self.assertRaises(ValueError):
            asyncio.run(payments.successful_payment_handler(self.mod,self._update("topup:1000:990",99000),None))
if __name__=="__main__": unittest.main()
