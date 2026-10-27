import asyncio
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from neyrobot_prod.marketplace_pipeline import generate_and_deliver
from neyrobot_prod.marketplace_pricing import MarketplaceQuote
from neyrobot_prod.marketplace_studio import Marketplace, Output, ProductProject, Stage
from neyrobot_prod.marketplace_usd_ledger import SQLiteUSDWalletLedger


class MarketplaceEndToEndTests(unittest.TestCase):
    def test_generation_delivery_and_real_sqlite_debit_happen_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "subs.db")
            with sqlite3.connect(database) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
                con.execute("INSERT INTO wallet VALUES(42, 5.00)")
            ledger = SQLiteUSDWalletLedger(database)
            ledger.initialize()
            project = ProductProject(
                output=Output.PHOTOS,
                marketplace=Marketplace.OZON,
                stage=Stage.APPROVAL,
                reference_ids=("telegram-photo",),
                brief="Фарфоровая чашка, объём 300 мл",
                attributes_confirmed=True,
            )
            quote = MarketplaceQuote(
                50, 50, 0.24, 0.50, 3, 3, 1, "gpt-image-2", "medium"
            )
            bot = AsyncMock()
            bot.send_document.side_effect = [
                SimpleNamespace(document=SimpleNamespace(file_id=f"tg-{index}"))
                for index in range(3)
            ]
            with patch(
                "neyrobot_prod.marketplace_pipeline.download_reference_images",
                new_callable=AsyncMock,
                return_value=("downloaded-reference",),
            ), patch(
                "neyrobot_prod.marketplace_pipeline.generate_product_image",
                side_effect=(b"main", b"angle", b"detail"),
            ) as provider:
                result = asyncio.run(generate_and_deliver(
                    project=project,
                    bot=bot,
                    chat_id=77,
                    provider_client=object(),
                    credit_ledger=ledger,
                    user_id=42,
                    quote=quote,
                    quote_accepted=True,
                    provider_enabled=True,
                    job_id="e2e-job",
                    artifact_dir=directory,
                ))
                self.assertEqual(len(result), 3)
                with self.assertRaisesRegex(RuntimeError, "повторный платный запуск"):
                    asyncio.run(generate_and_deliver(
                        project=project,
                        bot=bot,
                        chat_id=77,
                        provider_client=object(),
                        credit_ledger=ledger,
                        user_id=42,
                        quote=quote,
                        quote_accepted=True,
                        provider_enabled=True,
                        job_id="e2e-job",
                        artifact_dir=directory,
                    ))
            self.assertEqual(provider.call_count, 3)
            with sqlite3.connect(database) as con:
                balance = con.execute("SELECT usd FROM wallet WHERE user_id=42").fetchone()[0]
                rows = con.execute(
                    "SELECT status,COUNT(*) FROM credit_ledger GROUP BY status"
                ).fetchall()
            self.assertEqual(balance, 4.50)
            self.assertEqual(rows, [("charged", 1)])


if __name__ == "__main__":
    unittest.main()
