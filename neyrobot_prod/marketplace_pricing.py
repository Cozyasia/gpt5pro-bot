"""Truthful marketplace quotes derived from provider calls and project pricing.

The service price is fixed before generation. Provider input-token cost varies,
so the configured per-call provider cost is a conservative budget that includes
the documented image output price and reference-image input allowance.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from decimal import Decimal, ROUND_UP
from typing import Callable

from .marketplace_generation import GenerationRequest
from .marketplace_studio import Output


_OUTPUT_COUNTS = {
    Output.PHOTOS: (3, 3),
    Output.INFOGRAPHICS: (1, 2),
    Output.COMPLETE: (4, 5),
}


@dataclass(frozen=True)
class MarketplaceQuote:
    amount_cents: int
    credits: int
    provider_cost_usd: float
    retail_usd: float
    provider_image_count: int
    delivered_image_count: int
    selected_reference_count: int
    model: str
    quality: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "MarketplaceQuote":
        if not isinstance(value, dict):
            raise ValueError("Нет сохранённого расчёта стоимости.")
        try:
            quote = cls(**{field: value[field] for field in cls.__dataclass_fields__})
        except (KeyError, TypeError) as exc:
            raise ValueError("Сохранённый расчёт стоимости повреждён.") from exc
        if (
            not isinstance(quote.amount_cents, int)
            or isinstance(quote.amount_cents, bool)
            or quote.amount_cents <= 0
            or quote.credits <= 0
            or quote.provider_cost_usd <= 0
            or quote.retail_usd <= 0
            or quote.provider_image_count <= 0
            or quote.delivered_image_count <= 0
            or not quote.model
            or quote.quality not in {"low", "medium", "high"}
        ):
            raise ValueError("Сохранённый расчёт стоимости недействителен.")
        return quote


def build_marketplace_quote_service(
    *,
    retail_usd: Callable[[float], float],
    usd_to_credits: Callable[[float], float],
    provider_cost_per_image_usd: float,
    model: str,
    quality: str,
):
    unit_cost = Decimal(str(provider_cost_per_image_usd))
    if not unit_cost.is_finite() or unit_cost <= 0:
        raise ValueError("Marketplace provider cost must be positive")
    if not model.strip() or quality not in {"low", "medium", "high"}:
        raise ValueError("Marketplace model and quality must be configured")

    async def quote_service(*, request: GenerationRequest, user_id: int) -> MarketplaceQuote:
        del user_id  # price does not vary by user
        counts = _OUTPUT_COUNTS.get(request.output)
        if counts is None:
            raise ValueError("Для видео нужен отдельный видеоконвейер.")
        provider_count, delivered_count = counts
        provider_cost = unit_cost * provider_count
        provider_cost_float = float(provider_cost)
        retail = Decimal(str(retail_usd(provider_cost_float)))
        if not retail.is_finite() or retail <= 0:
            raise ValueError("Pricing policy returned an invalid retail price")
        amount_cents = int((retail * 100).quantize(Decimal("1"), rounding=ROUND_UP))
        return MarketplaceQuote(
            amount_cents=amount_cents,
            credits=int(round(float(usd_to_credits(amount_cents / 100)))),
            provider_cost_usd=round(provider_cost_float, 4),
            retail_usd=amount_cents / 100,
            provider_image_count=provider_count,
            delivered_image_count=delivered_count,
            selected_reference_count=min(16, len(request.reference_file_ids)),
            model=model.strip(),
            quality=quality,
        )

    return quote_service
