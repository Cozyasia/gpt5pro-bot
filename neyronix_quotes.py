"""Safe quote lifecycle for NEYRONIX paid operations.

In-memory pending quotes are short-lived and non-durable by design. A quote
must be reconfirmed if the process restarts; never debit on quote creation.
"""
from dataclasses import dataclass
from decimal import Decimal
from time import time
from uuid import uuid4
from neyronix_pricing import retail_credits

QUOTE_TTL_SECONDS = 300


@dataclass(frozen=True)
class PendingQuote:
    token: str
    user_id: int
    engine: str
    feature: str
    price_credits: Decimal
    created_at: float
    metadata: dict


def make_quote(*, user_id, engine, feature, provider_cost_usd, metadata=None, now=None):
    if not engine or not feature:
        raise ValueError("Engine and feature are required")
    price = retail_credits(provider_cost_usd)
    if price <= 0:
        raise ValueError("A paid quote must have positive price")
    return PendingQuote(
        token=uuid4().hex, user_id=int(user_id), engine=str(engine),
        feature=str(feature), price_credits=price,
        created_at=float(time() if now is None else now),
        metadata=dict(metadata or {}),
    )


def validate_confirmation(quote, *, user_id, token, now=None):
    """Confirm only the original customer, exact quote, and valid TTL."""
    if not isinstance(quote, PendingQuote):
        return False
    age = float(time() if now is None else now) - quote.created_at
    return (
        quote.user_id == int(user_id)
        and quote.token == str(token)
        and 0 <= age <= QUOTE_TTL_SECONDS
    )


def customer_summary(quote, available_credits):
    """Never expose provider costs, internal markup, or admin metadata."""
    if not isinstance(quote, PendingQuote):
        raise ValueError("Invalid quote")
    balance = Decimal(str(available_credits))
    if not balance.is_finite() or balance < 0:
        raise ValueError("Invalid balance")
    return {
        "engine": quote.engine,
        "feature": quote.feature,
        "price_credits": str(quote.price_credits),
        "balance_credits": str(balance),
        "remaining_credits": str(max(Decimal("0"), balance - quote.price_credits)),
        "can_afford": balance >= quote.price_credits,
    }
