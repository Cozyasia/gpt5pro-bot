"""Reference Studio: explicit provider capability and moderation-safe routing.

Pure preflight: no network, provider submissions, payments or image modifications.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReferenceKind(str, Enum):
    NONE = "none"
    OBJECT = "object"
    REAL_PERSON = "real_person"
    STYLIZED_PERSON = "stylized_person"


@dataclass(frozen=True)
class ProviderCapabilities:
    name: str
    image_to_video: bool
    real_person_reference: bool = False
    stylized_person_reference: bool = False
    max_seconds: int = 10


@dataclass(frozen=True)
class ReferenceDecision:
    allowed: bool
    provider: str | None
    reason: str


def decide_reference_route(
    kind: ReferenceKind,
    providers: tuple[ProviderCapabilities, ...],
    *,
    seconds: int,
    consent_confirmed: bool = False,
) -> ReferenceDecision:
    """Never assume a provider accepts human portraits without verified capability."""
    if seconds < 1:
        return ReferenceDecision(False, None, "Некорректная длительность.")
    if kind == ReferenceKind.NONE:
        return ReferenceDecision(False, None, "Не загружен референс.")
    if kind == ReferenceKind.REAL_PERSON and not consent_confirmed:
        return ReferenceDecision(False, None, "Подтвердите право использовать портрет.")
    for provider in providers:
        if not provider.image_to_video or seconds > provider.max_seconds:
            continue
        if kind == ReferenceKind.REAL_PERSON and not provider.real_person_reference:
            continue
        if kind == ReferenceKind.STYLIZED_PERSON and not provider.stylized_person_reference:
            continue
        return ReferenceDecision(True, provider.name, "Провайдер поддерживает заявленный тип референса.")
    return ReferenceDecision(
        False, None,
        "Нет подтверждённого провайдера для этого референса и длительности. "
        "Не отправляем изображение автоматически на другие модели."
    )
