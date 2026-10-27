import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from neyrobot_prod.marketplace_runtime import (
    configure_marketplace_runtime,
    initialize_marketplace_runtime,
)


class MarketplaceRuntimeTests(unittest.TestCase):
    def test_disabled_by_default(self):
        data = {"marketplace_image_client": object()}
        with patch.dict(os.environ, {"MARKETPLACE_PAID_GENERATION_ENABLED": "0"}):
            self.assertFalse(configure_marketplace_runtime(data))
        self.assertNotIn("marketplace_image_client", data)

    def test_requires_verified_wallet_and_quote(self):
        with patch.dict(os.environ, {"MARKETPLACE_PAID_GENERATION_ENABLED": "1"}):
            with self.assertRaisesRegex(RuntimeError, "verified wallet"):
                configure_marketplace_runtime({})

    def test_requires_api_key_before_initializing(self):
        ledger = type("Ledger", (), {
            name: AsyncMock() for name in (
                "reserve", "commit", "release", "mark_provider_started",
                "mark_provider_failed",
                "record_output", "mark_output_delivered", "mark_delivery_unknown",
                "recoverable_jobs",
            )
        })()
        with patch.dict(os.environ, {"MARKETPLACE_PAID_GENERATION_ENABLED": "1", "OPENAI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                configure_marketplace_runtime({}, ledger=ledger, quote_service=AsyncMock())

    def test_enabled_injects_verified_dependencies(self):
        ledger = type("Ledger", (), {
            name: AsyncMock() for name in (
                "reserve", "commit", "release", "mark_provider_started",
                "mark_provider_failed",
                "record_output", "mark_output_delivered", "mark_delivery_unknown",
                "recoverable_jobs",
            )
        })()
        data = {}
        with patch.dict(os.environ, {
            "MARKETPLACE_PAID_GENERATION_ENABLED": "1",
            "OPENAI_API_KEY": "test-only",
            "MARKETPLACE_IMAGE_MODEL": "gpt-image-2",
            "MARKETPLACE_ARTIFACT_DIR": "/tmp/marketplace-test",
        }):
            with patch("neyrobot_prod.marketplace_runtime.OpenAI") as client:
                self.assertTrue(configure_marketplace_runtime(data, ledger=ledger, quote_service=AsyncMock()))
        self.assertIs(data["marketplace_usd_ledger"], ledger)
        self.assertIs(data["marketplace_image_client"], client.return_value)
        self.assertEqual(data["marketplace_image_model"], "gpt-image-2")
        self.assertEqual(data["marketplace_artifact_dir"], "/tmp/marketplace-test")
        client.assert_called_once()

    def test_host_initializer_uses_production_wallet_and_pricing_functions(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "subs.db")
            with sqlite3.connect(database) as con:
                con.execute("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL)")
            data = {}
            with patch.dict(os.environ, {
                "MARKETPLACE_PAID_GENERATION_ENABLED": "1",
                "OPENAI_API_KEY": "test-only",
                "MARKETPLACE_PROVIDER_COST_PER_IMAGE_USD": "0.08",
            }):
                with patch("neyrobot_prod.marketplace_runtime.OpenAI"):
                    self.assertTrue(initialize_marketplace_runtime(
                        data,
                        db_path=database,
                        retail_usd=lambda cost: cost * 2,
                        usd_to_credits=lambda usd: usd * 100,
                    ))
            quote = data["marketplace_quote_service"]
            self.assertTrue(callable(quote))
            self.assertEqual(data["marketplace_usd_ledger"].db_path, database)


if __name__ == "__main__":
    unittest.main()
