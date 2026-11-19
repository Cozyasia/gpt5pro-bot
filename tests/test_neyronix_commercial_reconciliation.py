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
from neyrobot_prod.credit_store_v201 import catalog, resolve_pack, store_text, store_keyboard, methods_keyboard
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

    def test_telegram_store_rendering_and_callback_routes_offline(self):
        class FakeButton:
            def __init__(self, text, callback_data=None, url=None):
                self.text, self.callback_data, self.url = text, callback_data, url

        class FakeMarkup:
            def __init__(self, inline_keyboard):
                self.inline_keyboard = inline_keyboard

        ui = SimpleNamespace(
            InlineKeyboardButton=FakeButton, InlineKeyboardMarkup=FakeMarkup,
            _user_balance_get=lambda uid: 28.6,
            _credits_fmt_from_usd=lambda usd: f"{usd * 100:,.0f}".replace(",", " "),
            YOO_SBP_ENABLED=True, YOO_SBERPAY_ENABLED=True,
            YOO_TPAY_ENABLED=True, YOO_MIRPAY_ENABLED=True,
            YOOKASSA_PROVIDER_TOKEN="", CRYPTO_PAY_API_TOKEN="",
        )
        with patch("neyrobot_prod.credit_store_v201._runtime_module", return_value=None), patch.dict("os.environ", {
            "CREDIT_PACK_SMALL_CREDITS": "1000", "CREDIT_PACK_SMALL_RUB": "990",
            "CREDIT_PACK_MID_CREDITS": "3000", "CREDIT_PACK_MID_RUB": "2790",
            "CREDIT_PACK_BIG_CREDITS": "7000", "CREDIT_PACK_BIG_RUB": "6290",
        }):
            message = store_text(ui, 123)
            self.assertIn("Текущий баланс: 2 860", message)
            keyboard = store_keyboard(ui).inline_keyboard
            self.assertEqual(len(keyboard), 4)
            for row, (credits, rub) in zip(keyboard[:3], PACKAGES):
                self.assertEqual(len(row), 1)
                button = row[0]
                self.assertIn(f"{credits:,}".replace(",", " "), button.text)
                self.assertIn(f"{rub:,}".replace(",", " "), button.text)
                self.assertEqual(resolve_pack(credits, rub), (credits, rub))
                self.assertTrue(button.callback_data.startswith("credit:v201:pack:"))
            self.assertEqual(keyboard[-1][0].callback_data, "plan:root")
            for pack in catalog():
                methods = methods_keyboard(ui, pack).inline_keyboard
                callbacks = [button.callback_data for row in methods for button in row]
                self.assertIn(f"credit:v201:pay:yoo_sbp:{pack.key}", callbacks)
                self.assertIn(f"credit:v201:pay:yoo_all:{pack.key}", callbacks)
                self.assertIn("credit:v201:open", callbacks)
                self.assertFalse(any(":telegram:" in (cb or "") for cb in callbacks))
                self.assertFalse(any(":crypto:" in (cb or "") for cb in callbacks))

    def test_callback_checkout_dry_run_no_external_payment(self):
        import asyncio
        from unittest.mock import AsyncMock
        from neyrobot_prod import credit_store_v201 as store

        class StopHandler(Exception):
            pass

        telegram_ext = ModuleType("telegram.ext")
        telegram_ext.ApplicationHandlerStop = StopHandler
        replies = []
        created = []
        invoices = []
        message = SimpleNamespace(
            reply_text=AsyncMock(side_effect=lambda text, **kw: replies.append((text, kw)) or SimpleNamespace(chat=SimpleNamespace(id=123), message_id=456))
        )
        user = SimpleNamespace(id=123)
        query = SimpleNamespace(data="", answer=AsyncMock())
        update = SimpleNamespace(callback_query=query, effective_user=user, effective_message=message, effective_chat=SimpleNamespace(id=123))
        async def fake_creator(uid, credits, rub, method):
            created.append((uid, credits, rub, method))
            return {"id": "offline-id", "confirmation": {"confirmation_url": "https://example.invalid/offline"}}
        bot = SimpleNamespace(send_invoice=AsyncMock(side_effect=lambda **kw: invoices.append(kw)))
        context = SimpleNamespace(bot=bot, application=SimpleNamespace(create_task=lambda coro: coro.close()))
        runtime = SimpleNamespace(
            DB_PATH=self.db, BOT_TOKEN="fake", InlineKeyboardButton=lambda text, callback_data=None, url=None: SimpleNamespace(text=text, callback_data=callback_data, url=url),
            InlineKeyboardMarkup=lambda rows: SimpleNamespace(inline_keyboard=rows),
            _user_balance_get=lambda uid: 10.0, _credits_fmt_from_usd=lambda usd: str(int(usd * 100)),
            YOO_DIRECT_METHODS={"yoo_sbp": {"label": "SBP"}},
            _yoo_direct_configured=lambda: True,
            _yoo_create_credit_payment=fake_creator,
            _poll_yoo_credit_payment=AsyncMock(),
            YOOKASSA_PROVIDER_TOKEN="offline-test-token",
            LabeledPrice=lambda label, amount: SimpleNamespace(label=label, amount=amount),
        )
        async def press(data):
            query.data = data
            try:
                await store.callback(update, context)
            except StopHandler:
                return
            self.fail("Expected handler stop")

        with patch.dict(sys.modules, {"telegram.ext": telegram_ext}), patch.object(store, "_runtime_module", return_value=runtime):
            asyncio.run(press("credit:v201:open"))
            self.assertIn("Покупка кредитов", replies[-1][0])
            asyncio.run(press("credit:v201:pack:mid"))
            self.assertIn("3 000 кредитов за 2 790 ₽", replies[-1][0])
            asyncio.run(press("credit:v201:pay:yoo_sbp:mid"))
            self.assertEqual(created, [(123, 3000, 2790, "yoo_sbp")])
            self.assertIn("example.invalid/offline", replies[-1][1]["reply_markup"].inline_keyboard[0][0].url)
            asyncio.run(press("credit:v201:pay:telegram:small"))
            self.assertEqual(len(invoices), 1)
            self.assertEqual(invoices[0]["payload"], "topup:1000:990")
            self.assertEqual(invoices[0]["prices"][0].amount, 99000)
            self.assertEqual(invoices[0]["currency"], "RUB")
            asyncio.run(press("credit:v201:pay:yoo_sbp:invalid"))
            self.assertEqual(len(created), 1)
            self.assertIn("Покупка кредитов", replies[-1][0])
        self.assertEqual(len(invoices), 1)

    def test_provider_readiness_disabled_paths_never_create_payment(self):
        import asyncio
        from unittest.mock import AsyncMock
        from neyrobot_prod import credit_store_v201 as store

        replies = []
        msg = SimpleNamespace(reply_text=AsyncMock(side_effect=lambda text, **kw: replies.append(text)))
        update = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=123),
                                 effective_chat=SimpleNamespace(id=123))
        bot = SimpleNamespace(send_invoice=AsyncMock())
        ctx = SimpleNamespace(bot=bot)
        creator = AsyncMock()
        runtime = SimpleNamespace(
            YOO_SBP_ENABLED=False, YOO_SBERPAY_ENABLED=False, YOO_TPAY_ENABLED=False,
            YOO_MIRPAY_ENABLED=False, YOOKASSA_PROVIDER_TOKEN="", CRYPTO_PAY_API_TOKEN="",
            _yoo_direct_configured=lambda: False,
            _yoo_create_credit_payment=creator,
            InlineKeyboardButton=lambda text, callback_data=None, url=None: SimpleNamespace(
                text=text, callback_data=callback_data, url=url),
            InlineKeyboardMarkup=lambda rows: SimpleNamespace(inline_keyboard=rows),
        )
        pack = store.CreditPack("small", 1000, 990)
        buttons = [b.callback_data for row in store.methods_keyboard(runtime, pack).inline_keyboard for b in row]
        self.assertFalse(any(":yoo_sbp:" in b or ":yoo_sberpay:" in b or ":yoo_tpay:" in b
                             or ":yoo_mirpay:" in b or ":telegram:" in b or ":crypto:" in b
                             for b in buttons))
        asyncio.run(store._create_yoo(runtime, update, ctx, pack, "yoo_all"))
        asyncio.run(store._create_telegram_invoice(runtime, update, ctx, pack))
        asyncio.run(store._create_crypto(runtime, update, ctx, pack))
        creator.assert_not_awaited()
        bot.send_invoice.assert_not_awaited()
        self.assertEqual(len(replies), 3)
        self.assertIn("не настроена", replies[0])
        self.assertIn("не подключена", replies[1])
        self.assertIn("не подключён", replies[2])

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
