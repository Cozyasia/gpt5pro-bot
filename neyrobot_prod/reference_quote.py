"""No-charge Reference Studio quote gate.

Provider pricing must be explicitly configured and verified before a billable job.
No provider call or balance debit occurs in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP

from neyrobot_prod.reference_studio import (
    ProviderCapabilities, ReferenceDecision, ReferenceKind, decide_reference_route,
)


@dataclass(frozen=True)
class ReferenceQuote:
    allowed: bool
    provider: str | None
    credits: int | None
    reason: str


def quote_reference_job(
    kind: ReferenceKind,
    providers: tuple[ProviderCapabilities, ...],
    *,
    seconds: int,
    consent_confirmed: bool,
    previously_rejected: bool = False,
    verified_credits_per_second: dict[str, str] | None = None,
) -> ReferenceQuote:
    decision: ReferenceDecision = decide_reference_route(
        kind, providers, seconds=seconds,
        consent_confirmed=consent_confirmed,
        previously_rejected=previously_rejected,
    )
    if not decision.allowed or not decision.provider:
        return ReferenceQuote(False, None, None, decision.reason)
    rates = verified_credits_per_second or {}
    raw = rates.get(decision.provider)
    if raw is None:
        return ReferenceQuote(False, decision.provider, None,
                              "Стоимость провайдера не подтверждена; запуск заблокирован.")
    try:
        rate = Decimal(str(raw))
        if not rate.is_finite() or rate <= 0:
            raise InvalidOperation
        credits = int((rate * Decimal(seconds)).to_integral_value(rounding=ROUND_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return ReferenceQuote(False, decision.provider, None,
                              "Некорректный тариф провайдера; запуск заблокирован.")
    return ReferenceQuote(True, decision.provider, credits,
                          "Предварительная стоимость рассчитана. Перед списанием требуется подтверждение.")
