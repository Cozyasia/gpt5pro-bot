# -*- coding: utf-8 -*-
"""Server-side invoice and direct-payment validation for v119."""
from __future__ import annotations

import contextlib
import json
from typing import Any

from . import payments


def expected_invoice(mod: Any, payload: str) -> tuple[str, int] | None:
    raw = str(payload or "").strip()
    tier = ""
    months = 1
    if raw.startswith("{"):
        with contextlib.suppress(Exception):
            data = json.loads(raw)
            tier = str(data.get("tier") or "").lower().strip()
            months = int(data.get("months") or 1)
    elif raw.startswith("sub:"):
        with contextlib.suppress(Exception):
            _, tier, months_s = raw.split(":", 2)
            tier = tier.lower().strip()
            months = int(months_s or 1)
    elif raw.startswith("topup:"):
        with contextlib.suppress(Exception):
            _, credits_s, rub_s = raw.split(":", 2)
            resolver = getattr(mod, "_credit_pack_resolve", None)
            resolved = resolver(int(credits_s), int(rub_s)) if callable(resolver) else None
            if resolved:
                return "RUB", int(resolved[1]) * 100
        return None

    if tier not in {"start", "pro", "ultimate"} or months not in {1, 3, 6, 12}:
        return None

    # Telegram invoices are created by the legacy-compatible helper using
    # PLAN_PRICE_TABLE discounts. Reuse that server-side function when present.
    plan_payload = getattr(mod, "_plan_payload_and_amount", None)
    if callable(plan_payload):
        with contextlib.suppress(Exception):
            _payload, amount_rub, _title = plan_payload(tier, months)
            if int(amount_rub) > 0:
                return "RUB", int(amount_rub) * 100

    plan = (getattr(mod, "SUBS_TIERS", {}) or {}).get(tier) or {}
    amount_rub = int(plan.get("rub") or 0) * months
    return ("RUB", amount_rub * 100) if amount_rub > 0 else None


def expected_direct_subscription(mod: Any, tier: str, months: int) -> float:
    plan = (getattr(mod, "SUBS_TIERS", {}) or {}).get(str(tier or "").lower()) or {}
    return float(plan.get("rub") or 0) * max(1, int(months or 1))


async def precheckout_handler(mod: Any, update: Any, context: Any) -> None:
    query = getattr(update, "pre_checkout_query", None)
    if query is None:
        return
    expected = expected_invoice(mod, getattr(query, "invoice_payload", ""))
    actual_currency = str(getattr(query, "currency", "") or "").upper()
    actual_total = int(getattr(query, "total_amount", 0) or 0)
    if not expected:
        await query.answer(ok=False, error_message="Не удалось проверить счёт. Создайте новый счёт в меню бота.")
        return
    currency, total = expected
    if actual_currency != currency or actual_total != total:
        await query.answer(ok=False, error_message="Сумма счёта устарела или изменена. Создайте новый счёт.")
        return
    await query.answer(ok=True)


async def successful_payment_handler(mod: Any, update: Any, context: Any) -> None:
    sp = getattr(getattr(update, "message", None), "successful_payment", None)
    if sp is None:
        return
    expected = expected_invoice(mod, getattr(sp, "invoice_payload", ""))
    actual = (str(getattr(sp, "currency", "") or "").upper(), int(getattr(sp, "total_amount", 0) or 0))
    if not expected or actual != expected:
        raise RuntimeError(f"Telegram successful payment amount mismatch: expected={expected} actual={actual}")
    await payments.successful_payment_handler(mod, update, context)


def patch_runtime(mod: Any) -> bool:
    """Add direct YooKassa amount validation before transactional activation."""
    if getattr(payments.poll_yoo_subscription, "_prod_v119_guarded", False):
        mod._PROD_PAYMENT_GUARD_PATCHED = True
        return True
    original = payments.poll_yoo_subscription

    async def guarded(mod_arg: Any, context: Any, chat_id: int, message_id: int, user_id: int, payment_id: str, plan_key: str, months: int) -> None:
        payment = await mod_arg._yoo_get_payment(payment_id)
        if str((payment or {}).get("status") or "").lower() == "succeeded":
            amount = float(((payment or {}).get("amount") or {}).get("value") or 0)
            expected = expected_direct_subscription(mod_arg, plan_key, months)
            if expected <= 0 or abs(amount - expected) > 1.0:
                await payments._edit(
                    context,
                    chat_id,
                    message_id,
                    "⚠️ Оплата получена, но сумма не совпала с серверным тарифом. Подписка не активирована; повторно платить не нужно — обратитесь в поддержку.",
                )
                return
        await original(mod_arg, context, chat_id, message_id, user_id, payment_id, plan_key, months)

    guarded._prod_v119_guarded = True  # type: ignore[attr-defined]
    guarded._prod_v119_original = original  # type: ignore[attr-defined]
    payments.poll_yoo_subscription = guarded
    mod._PROD_PAYMENT_GUARD_PATCHED = True
    return True


__all__ = [
    "expected_invoice",
    "expected_direct_subscription",
    "precheckout_handler",
    "successful_payment_handler",
    "patch_runtime",
]
