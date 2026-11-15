"""NEYRONIX pricing policy. Pure calculations; no wallet or provider side effects.

This module intentionally does not change legacy balances or subscriptions.
Enable wallet migration only after balances and top-up conversion are audited.
"""
from decimal import Decimal, ROUND_CEILING

CREDITS_PER_USD = Decimal("10")
RETAIL_MULTIPLIER = Decimal("1.50")
CREDIT_QUANTUM = Decimal("0.1")


def retail_credits(provider_cost_usd, *, multiplier=RETAIL_MULTIPLIER):
    """Final customer-facing price; provider cost must remain server-side."""
    cost = Decimal(str(provider_cost_usd))
    rate = Decimal(str(multiplier))
    if not cost.is_finite() or cost < 0:
        raise ValueError("Invalid provider cost")
    if not rate.is_finite() or rate < 1:
        raise ValueError("Invalid retail multiplier")
    if cost == 0:
        return Decimal("0.0")
    raw = cost * rate * CREDITS_PER_USD
    return (raw / CREDIT_QUANTUM).to_integral_value(rounding=ROUND_CEILING) * CREDIT_QUANTUM


def credits_from_usd(usd):
    """Top-up USD equivalent; settlement and exchange rates handled separately."""
    amount = Decimal(str(usd))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Invalid top-up amount")
    return amount * CREDITS_PER_USD


def public_quote(*, model, mode, duration=None, provider_cost_usd):
    """Safe payload for user-facing UI: never include wholesale pricing."""
    quote = {"model": str(model), "mode": str(mode),
             "price_credits": str(retail_credits(provider_cost_usd))}
    if duration is not None:
        quote["duration_seconds"] = int(duration)
    return quote
