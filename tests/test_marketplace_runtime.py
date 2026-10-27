import os
import unittest
from unittest.mock import AsyncMock, patch

from neyrobot_prod.marketplace_runtime import configure_marketplace_runtime


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
        ledger = type("Ledger", (), {"reserve": AsyncMock(), "commit": AsyncMock(), "release": AsyncMock()})()
        with patch.dict(os.environ, {"MARKETPLACE_PAID_GENERATION_ENABLED": "1", "OPENAI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                configure_marketplace_runtime({}, ledger=ledger, quote_service=AsyncMock())

    def test_enabled_injects_verified_dependencies(self):
        ledger = type("Ledger", (), {"reserve": AsyncMock(), "commit": AsyncMock(), "release": AsyncMock()})()
        data = {}
        with patch.dict(os.environ, {"MARKETPLACE_PAID_GENERATION_ENABLED": "1", "OPENAI_API_KEY": "test-only"}):
            with patch("neyrobot_prod.marketplace_runtime.OpenAI") as client:
                self.assertTrue(configure_marketplace_runtime(data, ledger=ledger, quote_service=AsyncMock()))
        self.assertIs(data["marketplace_usd_ledger"], ledger)
        self.assertIs(data["marketplace_image_client"], client.return_value)
        client.assert_called_once()


if __name__ == "__main__":
    unittest.main()
