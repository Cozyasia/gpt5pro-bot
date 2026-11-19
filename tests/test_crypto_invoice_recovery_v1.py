import asyncio
import tempfile
import sys
from types import ModuleType
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from neyrobot_prod import crypto_invoice_recovery_v1 as recovery

class CryptoRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'test.db')
        self.mod = SimpleNamespace(DB_PATH=self.db, CRYPTO_PAY_API_TOKEN='test', _credits_to_usd=lambda n: n / 100)
        self.bot = SimpleNamespace(send_message=AsyncMock())
        recovery.register(self.db, '42', 123, 3000, 2790, '27.90', 'USDT', '123:mid')

    def tearDown(self):
        self.tmp.cleanup()

    def paid(self, **kwargs):
        return {'invoice_id': 42, 'status': 'paid', 'amount': '27.90', 'asset': 'USDT', 'payload': '123:mid'} | kwargs

    def test_restart_reconciliation_credits_once(self):
        async def check(token, invoice_id): return self.paid()
        asyncio.run(recovery.reconcile_once(self.mod, self.bot, check))
        asyncio.run(recovery.reconcile_once(self.mod, self.bot, check))
        from neyrobot_prod.db import connect
        with connect(self.db) as con:
            self.assertEqual(con.execute('select usd from wallet where user_id=123').fetchone()[0], 30)
            self.assertEqual(con.execute('select count(*) from payment_events').fetchone()[0], 1)
            self.assertEqual(con.execute('select status from crypto_store_invoices').fetchone()[0], 'paid')

    def test_wrong_provider_terms_are_not_credited(self):
        async def check(token, invoice_id): return self.paid(amount='0.01')
        asyncio.run(recovery.reconcile_once(self.mod, self.bot, check))
        from neyrobot_prod.db import connect
        with connect(self.db) as con:
            self.assertEqual(con.execute('select count(*) from crypto_store_invoices where status="pending"').fetchone()[0], 1)
            self.assertEqual(con.execute('select count(*) from payment_events').fetchone()[0], 0)

    def test_unavailable_provider_preserves_pending_invoice(self):
        async def check(token, invoice_id):
            raise TimeoutError('offline')
        asyncio.run(recovery.reconcile_once(self.mod, self.bot, check))
        from neyrobot_prod.db import connect
        with connect(self.db) as con:
            self.assertEqual(con.execute('select status from crypto_store_invoices').fetchone()[0], 'pending')

    def test_conflicting_payload_and_currency_are_rejected(self):
        for changes in ({'payload': '999:mid'}, {'asset': 'BTC'}, {'invoice_id': 99}):
            self.assertFalse(recovery._matches(self.paid(**changes), '42', '27.90', 'USDT', '123:mid'))

    def test_store_records_invoice_before_showing_link(self):
        from neyrobot_prod import credit_store_v201 as store
        class Client:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, url, **kwargs):
                return SimpleNamespace(json=lambda: {'ok': True, 'result': {'invoice_id': 43, 'bot_invoice_url': 'https://example.invalid/pay'}})
        async def reply(text, **kwargs):
            from neyrobot_prod.db import connect
            with connect(self.db) as con:
                self.assertEqual(con.execute("select user_id,credits,amount_rub from crypto_store_invoices where invoice_id='43'").fetchone(), (123,3000,2790))
        mod = SimpleNamespace(DB_PATH=self.db, CRYPTO_PAY_API_TOKEN='fake', CRYPTO_ASSET='USDT',
            InlineKeyboardButton=lambda text, callback_data=None, url=None: (text, callback_data, url),
            InlineKeyboardMarkup=lambda rows: rows)
        update = SimpleNamespace(effective_user=SimpleNamespace(id=123), effective_message=SimpleNamespace(reply_text=reply))
        with patch.object(store.httpx, 'AsyncClient', Client):
            asyncio.run(store._create_crypto(mod, update, None, store.CreditPack('mid',3000,2790)))

    def test_duplicate_registration_rejects_changed_terms(self):
        with self.assertRaises(ValueError):
            recovery.register(self.db, '42', 123, 7000, 6290, '27.90', 'USDT', '123:mid')

class StartupHookTests(unittest.TestCase):
    def test_recovery_is_scheduled_after_existing_post_init(self):
        from neyrobot_prod import credit_store_v201 as store
        prior = AsyncMock()
        app = SimpleNamespace(post_init=prior, bot=object(), bot_data={}, add_handler=lambda *a, **k: None)
        class Builder:
            def build(self): return app
        ext = ModuleType('telegram.ext')
        ext.ApplicationBuilder = Builder
        ext.CallbackQueryHandler = lambda *a, **k: object()
        ext.CommandHandler = lambda *a, **k: object()
        scheduled = []
        def schedule(coro, **kwargs):
            scheduled.append(kwargs.get('name'))
            coro.close()
        runtime = SimpleNamespace(BOT_TOKEN='fake')
        with patch.dict(sys.modules, {'telegram.ext':ext}), patch.object(store, '_BUILDER_HOOKED', False), \
             patch.object(store, '_runtime_module', return_value=runtime), patch.object(store.asyncio, 'create_task', side_effect=schedule):
            self.assertTrue(store.install_builder_hook())
            Builder().build()
            asyncio.run(app.post_init(app))
        prior.assert_awaited_once_with(app)
        self.assertEqual(scheduled, ['credit-store-payment-recovery'])

class YooRecoveryTests(unittest.TestCase):
    def test_succeeded_payment_is_recovered_once_with_matching_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'db')
            mod = SimpleNamespace(DB_PATH=db, _credits_to_usd=lambda n: n / 100)
            bot = SimpleNamespace(send_message=AsyncMock())
            recovery.register_yoo(db, 'payment-1', 123, 3000, 2790)
            async def status(pid):
                return {'id': pid, 'status': 'succeeded', 'amount': {'value':'2790.00','currency':'RUB'},
                        'metadata': {'kind':'credit_topup','user_id':'123','credits':'3000','amount_rub':'2790'}}
            asyncio.run(recovery.reconcile_yoo_once(mod, bot, status))
            asyncio.run(recovery.reconcile_yoo_once(mod, bot, status))
            from neyrobot_prod.db import connect
            with connect(db) as con:
                self.assertEqual(con.execute('select usd from wallet where user_id=123').fetchone()[0], 30)
                self.assertEqual(con.execute('select count(*) from payment_events').fetchone()[0], 1)

    def test_mismatched_yoo_metadata_cannot_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'db')
            mod = SimpleNamespace(DB_PATH=db)
            recovery.register_yoo(db, 'p', 123, 3000, 2790)
            async def status(pid):
                return {'id': pid, 'status': 'succeeded', 'amount': {'value':'2790.00','currency':'RUB'},
                        'metadata': {'kind':'credit_topup','user_id':'999','credits':'3000','amount_rub':'2790'}}
            asyncio.run(recovery.reconcile_yoo_once(mod, SimpleNamespace(send_message=AsyncMock()), status))
            from neyrobot_prod.db import connect
            with connect(db) as con:
                self.assertEqual(con.execute('select count(*) from payment_events').fetchone()[0], 0)

if __name__ == '__main__': unittest.main()
