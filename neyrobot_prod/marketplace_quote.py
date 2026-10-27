"""Bind a USD quote to the exact immutable product generation request."""
from __future__ import annotations

import hashlib
import json


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
