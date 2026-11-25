"""Fail-closed pricing and settlement for a video translation attempt."""
from dataclasses import dataclass
import math

from .translation_segments import estimate_provider_cost
from .translation_credit_ledger import execute


@dataclass(frozen=True)
class TranslationQuote:
    duration: float
    provider_cost: float
    retail_cost: float
    credits: float


@dataclass(frozen=True)
class TranslationResult:
    state: str
    provider_cost: float
    retail_cost: float
    credits: float


def make_quote(duration, *, pricing, retail_quote):
    """Create immutable terms for display and later confirmation."""
    if not isinstance(pricing, dict) or not callable(retail_quote):
        raise ValueError('pricing unavailable')
    try:
        duration = float(duration)
        provider = float(estimate_provider_cost(duration, **pricing))
        retail, credits = retail_quote(provider)
        retail, credits = float(retail), float(credits)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('pricing unavailable') from exc
    if (not math.isfinite(duration) or any(not math.isfinite(x) or x <= 0
        for x in (provider, retail, credits)) or retail < provider):
        raise ValueError('invalid retail quote')
    return TranslationQuote(duration, provider, retail, credits)


async def run_quoted(db_path, request_id, user_id, quote, *, render, deliver):
    """Use the exact quote shown to the customer; no recalculation on launch."""
    if not isinstance(quote, TranslationQuote):
        raise ValueError('a confirmed quote is required')
    # Validate even constructed or deserialized quotes at the money boundary.
    if (not math.isfinite(quote.duration) or not 2 <= quote.duration <= 180 or
        any(not math.isfinite(x) or x <= 0 for x in
            (quote.provider_cost, quote.retail_cost, quote.credits)) or
        quote.retail_cost < quote.provider_cost):
        raise ValueError('invalid confirmed quote')
    state = await execute(db_path, request_id, user_id, provider_cost=quote.provider_cost,
                          retail_cost=quote.retail_cost, credits=quote.credits,
                          render=render, deliver=deliver)
    return TranslationResult(state, quote.provider_cost, quote.retail_cost, quote.credits)


async def run(db_path, request_id, user_id, duration, *, pricing, retail_quote, render, deliver):
    quote = make_quote(duration, pricing=pricing, retail_quote=retail_quote)
    return await run_quoted(db_path, request_id, user_id, quote, render=render, deliver=deliver)
