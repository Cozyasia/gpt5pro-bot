"""Explicit NEYRONIX quote-to-legacy-unit bridge (no wallet side effects).

Do not infer legacy credit exchange rates from package prices or from
NEYRONIX's independent CREDITS_PER_USD constant. The caller must supply a
verified runtime conversion rate before showing a spendable quote.
"""
from decimal import Decimal, ROUND_CEILING
from neyronix_pricing import retail_credits, CREDITS_PER_USD

def legacy_credit_quote(provider_cost_usd, *, legacy_credits_per_usd):
    rate = Decimal(str(legacy_credits_per_usd))
    if not rate.is_finite() or rate <= 0:
        raise ValueError("Verified legacy credit conversion rate required")
    neyronix_price = retail_credits(provider_cost_usd)
    retail_usd = neyronix_price / CREDITS_PER_USD
    # Whole legacy credits: never round down the amount charged.
    legacy_credits = (retail_usd * rate).to_integral_value(rounding=ROUND_CEILING)
    return {
        "price_credits": str(legacy_credits),
        "retail_usd": str(retail_usd),
        "unit": "legacy_credits",
    }
