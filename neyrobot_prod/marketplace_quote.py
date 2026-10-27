"""Bind a USD quote to the exact immutable product generation request."""
from __future__ import annotations

import hashlib
import json
import time

from .marketplace_pricing import MarketplaceQuote


def fingerprint(request) -> str:
    payload = {
        "output": request.output.value,
        "marketplace": request.marketplace,
        "reference_file_ids": list(request.reference_file_ids),
        "brief": request.brief,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validated_quote_cents(user_data, request) -> int:
    amount = user_data.get("mp_quoted_usd_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("Сначала получите действительную стоимость в USD.")
    if user_data.get("mp_quote_fingerprint") != fingerprint(request):
        raise ValueError("Задание изменилось. Необходимо заново рассчитать стоимость.")
    return amount


def validated_marketplace_quote(
    user_data,
    request,
    *,
    now: float | None = None,
    max_age_seconds: int = 900,
) -> MarketplaceQuote:
    amount = validated_quote_cents(user_data, request)
    created = user_data.get("mp_quote_created_ts")
    current = time.time() if now is None else now
    if not isinstance(created, (int, float)) or current - float(created) > max_age_seconds:
        raise ValueError("Стоимость устарела. Рассчитайте её заново.")
    quote = MarketplaceQuote.from_dict(user_data.get("mp_quote_details"))
    if quote.amount_cents != amount:
        raise ValueError("Сохранённая стоимость не совпадает с подтверждённой.")
    return quote
