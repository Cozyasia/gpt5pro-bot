import asyncio
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from neyrobot_prod.marketplace_pipeline import recover_deliveries
from neyrobot_prod.marketplace_usd_ledger import SQLiteUSDWalletLedger


class MarketplaceBillingRecoveryTests(unittest.TestCase):
    def test_ready_files_are_recoverable_after_new_ledger_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "wallet.sqlite")
            artifact = os.path.join(directory, "card.png")
            with open(artifact, "wb") as output:
                output.write(b"png")
            with sqlite3.connect(database) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
                con.execute("INSERT INTO wallet VALUES(7, 5.00)")
            first = SQLiteUSDWalletLedger(database)
            first.initialize()
            reservation = asyncio.run(first.reserve(
                user_id=7,
                amount=50,
                idempotency_key="recover-me",
                provider_cost_usd=0.20,
                credits=50,
                expected_outputs=1,
                metadata={"chat_id": 77},
            ))
            asyncio.run(first.mark_provider_started(reservation, operation_id="openai-started"))
            asyncio.run(first.record_output(reservation, index=0, path=artifact))
            asyncio.run(first.mark_delivery_unknown(reservation, error="telegram timeout"))

            restarted = SQLiteUSDWalletLedger(database)
            restarted.initialize()
            jobs = asyncio.run(restarted.recoverable_jobs())

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].key, "recover-me")
            self.assertEqual(jobs[0].status, "delivery_unknown")
            self.assertEqual(jobs[0].metadata["chat_id"], 77)
            self.assertEqual(jobs[0].outputs[0].path, artifact)
            self.assertFalse(jobs[0].outputs[0].delivered)

            bot = AsyncMock()
            bot.send_document.return_value = SimpleNamespace(
                document=SimpleNamespace(file_id="recovered-file")
            )
            recovered_count = asyncio.run(recover_deliveries(bot=bot, ledger=restarted))
            self.assertEqual(recovered_count, 1)
            bot.send_document.assert_awaited_once()
            with sqlite3.connect(database) as con:
                balance = con.execute("SELECT usd FROM wallet WHERE user_id=7").fetchone()[0]
                status = con.execute(
                    "SELECT status FROM credit_ledger WHERE tx_id=?", (reservation.tx_id,)
                ).fetchone()[0]
            self.assertEqual(balance, 4.50)
            self.assertEqual(status, "charged")


if __name__ == "__main__":
    unittest.main()
