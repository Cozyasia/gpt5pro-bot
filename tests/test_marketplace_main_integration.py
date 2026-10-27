import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import AsyncMock
from telegram.ext import ApplicationHandlerStop

from neyrobot_prod.marketplace_studio import Marketplace, Output, ProductProject, Stage
from neyrobot_prod.marketplace_telegram import load, save

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("PUBLIC_URL", "https://test.onrender.com")
os.environ.setdefault("OPENAI_API_KEY", "test-only")

import main


class MarketplaceMainIntegrationTests(unittest.TestCase):
    def test_app_bootstrap_passes_verified_host_financial_dependencies(self):
        app = SimpleNamespace(bot_data={})
        with patch(
            "neyrobot_prod.marketplace_runtime.initialize_marketplace_runtime",
            return_value=True,
        ) as initialize:
            self.assertTrue(main._configure_marketplace_app(app))
        initialize.assert_called_once_with(
            app.bot_data,
            db_path=main.DB_PATH,
            retail_usd=main._retail_usd,
            usd_to_credits=main._usd_to_credits,
        )

    def test_app_bootstrap_fails_closed_without_crashing_other_modes(self):
        app = SimpleNamespace(bot_data={})
        with patch(
            "neyrobot_prod.marketplace_runtime.initialize_marketplace_runtime",
            side_effect=RuntimeError("wallet invalid"),
        ):
            self.assertFalse(main._configure_marketplace_app(app))
        self.assertNotIn("marketplace_usd_ledger", app.bot_data)

    def test_restart_recovery_uses_injected_ledger(self):
        ledger = object()
        app = SimpleNamespace(bot=object(), bot_data={"marketplace_usd_ledger": ledger})
        with patch(
            "neyrobot_prod.marketplace_pipeline.recover_deliveries",
            new_callable=AsyncMock,
            return_value=2,
        ) as recover:
            self.assertEqual(asyncio.run(main._recover_marketplace_after_restart(app)), 2)
        recover.assert_awaited_once_with(bot=app.bot, ledger=ledger)

    def test_generic_stale_cleanup_does_not_release_durable_marketplace_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "subs.db")
            with sqlite3.connect(database) as con:
                con.execute(
                    "CREATE TABLE credit_ledger("
                    "tx_id TEXT PRIMARY KEY,user_id INTEGER,feature TEXT,status TEXT,"
                    "created_ts INTEGER,updated_ts INTEGER)"
                )
                con.execute(
                    "INSERT INTO credit_ledger VALUES('market',1,'marketplace_cards',"
                    "'reserved',0,0)"
                )
                con.execute(
                    "INSERT INTO credit_ledger VALUES('legacy',1,'other','reserved',0,0)"
                )
                main._credit_release_stale(con.cursor(), 1)
                con.commit()
                rows = dict(con.execute(
                    "SELECT tx_id,status FROM credit_ledger ORDER BY tx_id"
                ))
            self.assertEqual(rows["market"], "reserved")
            self.assertEqual(rows["legacy"], "released_timeout")

    def test_voice_brief_downloads_transcribes_and_shows_confirmable_russian_text(self):
        user_data = {}
        save(user_data, ProductProject(
            output=Output.PHOTOS,
            marketplace=Marketplace.OZON,
            stage=Stage.BRIEF,
            reference_ids=("photo",),
        ))
        message = SimpleNamespace(
            voice=SimpleNamespace(file_id="voice-id", mime_type="audio/ogg"),
            audio=None,
            reply_text=AsyncMock(),
        )
        tg_file = SimpleNamespace(download_to_memory=AsyncMock())
        tg_file.download_to_memory.side_effect = lambda out: out.write(b"voice-bytes")
        context = SimpleNamespace(
            user_data=user_data,
            bot=SimpleNamespace(get_file=AsyncMock(return_value=tg_file)),
        )
        update = SimpleNamespace(effective_message=message, message=message)
        with patch.object(
            main, "_stt_transcribe_bytes", new=AsyncMock(return_value="Фарфоровая чашка 300 мл")
        ):
            with self.assertRaises(ApplicationHandlerStop):
                asyncio.run(main._marketplace_voice_priority(update, context))
        self.assertEqual(load(user_data).stage, Stage.REVIEW)
        self.assertIn("Фарфоровая чашка 300 мл", message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
import asyncio
