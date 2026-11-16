"""Offline commercial reconciliation: purchase, charge, reserve, refund and margin."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from neyronix_pricing import CREDITS_PER_USD, retail_credits
import sys
from unittest.mock import patch
from types import ModuleType

# Store display tests do not make HTTP requests; CI installs only stdlib dependencies.
if 'httpx' not in sys.modules:
    try:
        import httpx
    except ImportError:
        sys.modules['httpx'] = ModuleType('httpx')
from neyrobot_prod.credit_store_v201 import catalog, resolve_pack, store_text
from neyrobot_prod.payments import process_once
from property_video_billing import reserve, mark_delivered, refund_before_submission, record_operation, record_result

PACKAGES = ((1000, 990), (3000, 2790), (7000, 6290))
PROVIDER_COSTS = ("0.01", "0.70", "2.35", "5.00")

class OfflineCommercialReconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "commercial.sqlite")
        self.mod = SimpleNamespace(DB_PATH=self.db, _credits_to_usd=lambda credits: credits / 100.0)

    def balance(self):
        with sqlite3.connect(self.db) as con:
            row = con.execute("SELECT usd FROM wallet WHERE user_id=123").fetchone()
            return float(row[0]) if row else 0.0

    def buy(self, credits, rub, payment_id):
        return process_once(self.mod, provider="offline", payment_id=payment_id,
                            user_id=123, kind="credit_topup", amount=rub,
                            currency="RUB", metadata={"credits": credits, "amount_rub": rub})

    def test_store_display_and_checkout_catalog_match_offline_settlement(self):
        from unittest.mock import patch
        with patch("neyrobot_prod.credit_store_v201._runtime_module", return_value=None), patch.dict("os.environ", {
            "CREDIT_PACK_SMALL_CREDITS": "1000", "CREDIT_PACK_SMALL_RUB": "990",
            "CREDIT_PACK_MID_CREDITS": "3000", "CREDIT_PACK_MID_RUB": "2790",
            "CREDIT_PACK_BIG_CREDITS": "7000", "CREDIT_PACK_BIG_RUB": "6290",
        }):
            packs = catalog()
            self.assertEqual([(p.credits, p.rub) for p in packs], list(PACKAGES))
            self.assertNotIn("1 кредит = 1 ₽", store_text(self.mod))
            for credits, rub in PACKAGES:
                self.assertEqual(resolve_pack(credits, rub), (credits, rub))
                self.assertIsNone(resolve_pack(credits, rub + 1))
                self.assertAlmostEqual(credits / float(CREDITS_PER_USD), credits / 100)

    def test_all_packages_purchase_spend_refund_and_margin(self):
        self.assertEqual(int(CREDITS_PER_USD), 100)
        for credits, rub in PACKAGES:
            with self.subTest(package=credits):
                self.setUp()
                first = self.buy(credits, rub, "purchase")
                self.assertTrue(first.processed)
                self.assertEqual(first.credits, credits)
                self.assertAlmostEqual(self.balance(), credits / 100)
                duplicate = self.buy(credits, rub, "purchase")
                self.assertTrue(duplicate.duplicate)
                self.assertAlmostEqual(self.balance(), credits / 100)
                cost = 0.70
                price_credits = int(retail_credits(cost))
                price_usd = price_credits / 100
                self.assertEqual(price_credits, 140)
                self.assertEqual(reserve(self.db, "success", 123, price_usd, provider_cost_usd=cost), "reserved")
                self.assertEqual(reserve(self.db, "success", 123, price_usd, provider_cost_usd=cost), "reserved")
                record_operation(self.db, "success", "offline-operation")
                self.assertTrue(record_result(self.db, "success", "/tmp/fake-result.mp4"))
                self.assertTrue(mark_delivered(self.db, "success", telegram_file_id="fake-file"))
                self.assertTrue(mark_delivered(self.db, "success", telegram_file_id="fake-file"))
                self.assertAlmostEqual(self.balance(), (credits - 140) / 100)
                self.assertEqual(reserve(self.db, "cancel", 123, price_usd), "reserved")
                self.assertTrue(refund_before_submission(self.db, "cancel"))
                self.assertFalse(refund_before_submission(self.db, "cancel"))
                self.assertAlmostEqual(self.balance(), (credits - 140) / 100)
                with sqlite3.connect(self.db) as con:
                    rows = con.execute("SELECT status, COUNT(*) FROM credit_ledger GROUP BY status").fetchall()
                self.assertEqual(dict(rows), {"charged": 1, "released": 1})
                # Revenue is RUB received, not wallet USD; exchange rate is deliberately not assumed.
                self.assertGreater(rub, 0)

    def test_cost_markup_rounding_and_provider_margin(self):
        for raw in PROVIDER_COSTS:
            with self.subTest(cost=raw):
                cost = float(raw)
                credits = int(retail_credits(raw))
                self.assertEqual(credits % 5, 0)
                retail_usd = credits / 100
                self.assertGreaterEqual(retail_usd + 1e-9, cost * 2)
                self.assertGreaterEqual(retail_usd - cost + 1e-9, cost)

    def test_insufficient_balance_and_refund_after_submission(self):
        self.buy(1000, 990, "purchase")
        self.assertEqual(reserve(self.db, "too-large", 123, 11.0), "insufficient")
        self.assertEqual(reserve(self.db, "submitted", 123, 1.4), "reserved")
        record_operation(self.db, "submitted", "provider-request")
        self.assertFalse(refund_before_submission(self.db, "submitted"))
        self.assertAlmostEqual(self.balance(), 10.0)

if __name__ == "__main__":
    unittest.main()
