"""Fail-closed runtime bootstrap for product image generation.

This module does not create a wallet or guess a production database path.
The host application must explicitly supply a verified wallet ledger and
an async quote service whose prices are in USD cents.
"""
from __future__ import annotations

import os
from openai import OpenAI


def configure_marketplace_runtime(bot_data, *, ledger=None, quote_service=None):
    """Inject verified dependencies; never enable billing implicitly."""
    bot_data.pop("marketplace_usd_ledger", None)
    bot_data.pop("marketplace_quote_service", None)
    bot_data.pop("marketplace_image_client", None)

    if os.getenv("MARKETPLACE_PAID_GENERATION_ENABLED") != "1":
        return False
    if ledger is None or quote_service is None:
        raise RuntimeError("Marketplace billing requires verified wallet ledger and USD-cent quote service")
    if not callable(quote_service):
        raise TypeError("Marketplace quote service must be callable")
    if not all(callable(getattr(ledger, method, None)) for method in ("reserve", "commit", "release")):
        raise TypeError("Marketplace ledger must implement reserve, commit and release")
    # Do not accept an arbitrary object as the production billing ledger.\n    # The host must initialize and validate the wallet schema before injection.\n    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for marketplace image generation")
    client = OpenAI(api_key=api_key, timeout=120, max_retries=0)
    bot_data["marketplace_usd_ledger"] = ledger
    bot_data["marketplace_quote_service"] = quote_service
    bot_data["marketplace_image_client"] = client
    return True
