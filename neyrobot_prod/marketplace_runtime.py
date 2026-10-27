"""Fail-closed runtime bootstrap for product image generation.

This module does not create a wallet or guess a production database path.
The host application must explicitly supply a verified wallet ledger and
an async quote service whose prices are in USD cents.
"""
from __future__ import annotations

import os
from openai import OpenAI

from .marketplace_pricing import build_marketplace_quote_service
from .marketplace_usd_ledger import SQLiteUSDWalletLedger


_LEDGER_METHODS = (
    "reserve",
    "commit",
    "release",
    "mark_provider_started",
    "mark_provider_failed",
    "record_output",
    "mark_output_delivered",
    "mark_delivery_unknown",
    "recoverable_jobs",
)


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
    if not all(callable(getattr(ledger, method, None)) for method in _LEDGER_METHODS):
        raise TypeError("Marketplace ledger does not implement the durable billing contract")
    # The host initializes and validates the production wallet before injection.
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for marketplace image generation")
    client = OpenAI(api_key=api_key, timeout=120, max_retries=0)
    bot_data["marketplace_usd_ledger"] = ledger
    bot_data["marketplace_quote_service"] = quote_service
    bot_data["marketplace_image_client"] = client
    bot_data["marketplace_image_model"] = (
        os.getenv("MARKETPLACE_IMAGE_MODEL") or "gpt-image-2"
    ).strip()
    bot_data["marketplace_image_quality"] = (
        os.getenv("MARKETPLACE_IMAGE_QUALITY") or "medium"
    ).strip()
    bot_data["marketplace_artifact_dir"] = (
        os.getenv("MARKETPLACE_ARTIFACT_DIR") or "/data/marketplace_jobs"
    ).strip()
    return True


def initialize_marketplace_runtime(
    bot_data,
    *,
    db_path: str,
    retail_usd,
    usd_to_credits,
):
    """Build and inject production dependencies using host pricing functions."""
    # Draft persistence is independent from paid generation and keeps the wizard
    # routable across process restarts before a provider or wallet is involved.
    bot_data["marketplace_db_path"] = db_path
    if os.getenv("MARKETPLACE_PAID_GENERATION_ENABLED") != "1":
        return configure_marketplace_runtime(bot_data)
    model = (os.getenv("MARKETPLACE_IMAGE_MODEL") or "gpt-image-2").strip()
    quality = (os.getenv("MARKETPLACE_IMAGE_QUALITY") or "medium").strip()
    try:
        unit_cost = float(
            os.getenv("MARKETPLACE_PROVIDER_COST_PER_IMAGE_USD") or "0.35"
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid marketplace provider cost") from exc

    ledger = SQLiteUSDWalletLedger(db_path)
    ledger.initialize()
    quote_service = build_marketplace_quote_service(
        retail_usd=retail_usd,
        usd_to_credits=usd_to_credits,
        provider_cost_per_image_usd=unit_cost,
        model=model,
        quality=quality,
    )
    return configure_marketplace_runtime(
        bot_data,
        ledger=ledger,
        quote_service=quote_service,
    )
