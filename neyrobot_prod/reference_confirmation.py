"""One-time user confirmation for a verified Reference Studio quote.

This module does not call providers or debit user balances.
"""
from __future__ import annotations

from dataclasses import dataclass
from secrets import token_urlsafe

from neyrobot_prod.reference_quote import ReferenceQuote


@dataclass(frozen=True)
class PendingReferenceApproval:
    token: str
    user_id: int
    provider: str
    credits: int
    seconds: int


def stage_reference_approval(
    quote: ReferenceQuote, *, user_id: int, seconds: int
) -> PendingReferenceApproval:
    """Create an approval only after verified routing and pricing preflight."""
    if (
        not quote.allowed or not quote.provider
        or not isinstance(quote.credits, int) or isinstance(quote.credits, bool)
        or quote.credits <= 0 or user_id <= 0 or seconds <= 0
    ):
        raise ValueError("Reference quote is not eligible for confirmation")
    return PendingReferenceApproval(
        token=token_urlsafe(24), user_id=user_id,
        provider=quote.provider, credits=quote.credits, seconds=seconds,
    )


def approve_reference_job(
    pending: PendingReferenceApproval | None, *,
    user_id: int, token: str, current_quote: ReferenceQuote,
    confirmed: bool,
) -> bool:
    """Reject stale quotes, cross-user approvals and unconfirmed jobs.

    The caller must consume/remove the pending approval atomically before any
    payment or provider call; this pure guard cannot enforce one-time storage.
    """
    return bool(
        confirmed and pending is not None
        and user_id == pending.user_id
        and token == pending.token and bool(token)
        and current_quote.allowed
        and current_quote.provider == pending.provider
        and current_quote.credits == pending.credits
        and isinstance(current_quote.credits, int)
        and not isinstance(current_quote.credits, bool)
        and pending.credits > 0
    )
