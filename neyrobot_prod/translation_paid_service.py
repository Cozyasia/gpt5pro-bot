"""Fail-closed pricing and settlement for a video translation attempt."""
from dataclasses import dataclass
import math

from .translation_segments import estimate_provider_cost
from .translation_credit_ledger import execute


@dataclass(frozen=True)
class TranslationResult:
    state: str
    provider_cost: float
    retail_cost: float
    credits: float


async def run(db_path, request_id, user_id, duration, *, pricing, retail_quote, render, deliver):
    """Quote all stages before any paid work; deliver and settle once.

    pricing must contain explicit estimates for STT, translation, TTS and each
    Kling identify-face / lip-sync request. No provider price is guessed here.
    """
    if not isinstance(pricing, dict) or not callable(retail_quote):
        raise ValueError('pricing unavailable')
    try:
        provider = float(estimate_provider_cost(duration, **pricing))
        retail, credits = retail_quote(provider)
        retail, credits = float(retail), float(credits)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('pricing unavailable') from exc
    if any(not math.isfinite(x) or x <= 0 for x in (provider, retail, credits)) or retail < provider:
        raise ValueError('invalid retail quote')
    state = await execute(db_path, request_id, user_id, provider_cost=provider,
                          retail_cost=retail, credits=credits, render=render, deliver=deliver)
    return TranslationResult(state, provider, retail, credits)
