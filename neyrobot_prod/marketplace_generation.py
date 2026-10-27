"""Fail-closed product generation preparation; no provider calls or billing.

Keeps marketplace intake independent from paid image/video executors until
provider capability, cost, and consent have been explicitly verified.
"""
from __future__ import annotations

from dataclasses import dataclass

from .marketplace_studio import Output, ProductProject, Stage


@dataclass(frozen=True)
class GenerationRequest:
    output: Output
    marketplace: str
    reference_file_ids: tuple[str, ...]
    brief: str


def prepare_generation(project: ProductProject) -> GenerationRequest:
    """Validate a complete project before downloading or generating media."""
    if project.stage != Stage.APPROVAL or not project.attributes_confirmed:
        raise ValueError("Сначала подтвердите характеристики товара.")
    if project.output is None or project.marketplace is None:
        raise ValueError("Выберите результат и маркетплейс.")
    if not project.reference_ids:
        raise ValueError("Загрузите фотографии товара.")
    if not project.brief.strip():
        raise ValueError("Добавьте описание товара.")
    return GenerationRequest(
        output=project.output,
        marketplace=project.marketplace.value,
        reference_file_ids=project.reference_ids,
        brief=project.brief,
    )


def ensure_paid_generation_ready(*, provider_enabled: bool, quoted_credits: int | None,
                                 quote_accepted: bool) -> None:
    """Refuse paid execution until a provider and explicit price consent exist."""
    if not provider_enabled:
        raise RuntimeError("Генератор карточек товара пока не подключён.")
    if quoted_credits is None or quoted_credits <= 0:
        raise ValueError("Нет подтверждённой стоимости генерации.")
    if not quote_accepted:
        raise ValueError("Необходимо согласие на списание кредитов.")
