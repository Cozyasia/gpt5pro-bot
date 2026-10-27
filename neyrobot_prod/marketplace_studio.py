"""Pure state transitions for marketplace product-card intake.

No Telegram, provider, network, or credit side effects. The adapter must persist
session snapshots and call these functions before generating anything.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Output(str, Enum):
    PHOTOS = "photos"
    INFOGRAPHICS = "infographics"
    VIDEO = "video"
    COMPLETE = "complete"


class Marketplace(str, Enum):
    WILDBERRIES = "wildberries"
    OZON = "ozon"
    YANDEX = "yandex"
    AMAZON = "amazon"
    GENERIC = "generic"


class Stage(str, Enum):
    OUTPUT = "output"
    MARKETPLACE = "marketplace"
    REFERENCES = "references"
    BRIEF = "brief"
    REVIEW = "review"
    APPROVAL = "approval"


@dataclass(frozen=True)
class ProductProject:
    output: Output | None = None
    marketplace: Marketplace | None = None
    stage: Stage = Stage.OUTPUT
    reference_ids: tuple[str, ...] = ()
    brief: str = ""
    attributes_confirmed: bool = False
    approved: bool = False


def select_output(project: ProductProject, output: Output) -> ProductProject:
    if project.stage != Stage.OUTPUT:
        raise ValueError("Output selection is not expected")
    return replace(project, output=Output(output), stage=Stage.MARKETPLACE)


def select_marketplace(project: ProductProject, marketplace: Marketplace) -> ProductProject:
    if project.stage != Stage.MARKETPLACE:
        raise ValueError("Marketplace selection is not expected")
    return replace(project, marketplace=Marketplace(marketplace), stage=Stage.REFERENCES)


def add_references(project: ProductProject, reference_ids: tuple[str, ...]) -> ProductProject:
    if project.stage != Stage.REFERENCES:
        raise ValueError("Reference upload is not expected")
    unique = tuple(dict.fromkeys((*project.reference_ids, *(str(x) for x in reference_ids if x))))
    if len(unique) > 30:
        raise ValueError("Maximum 30 references per project")
    return replace(project, reference_ids=unique)


def continue_after_references(project: ProductProject) -> ProductProject:
    if project.stage != Stage.REFERENCES:
        raise ValueError("Continue is not expected")
    if not project.reference_ids:
        raise ValueError("Upload at least one reference photo")
    return replace(project, stage=Stage.BRIEF)


def set_brief(project: ProductProject, text: str) -> ProductProject:
    if project.stage != Stage.BRIEF:
        raise ValueError("Brief is not expected")
    if not text.strip():
        raise ValueError("Brief cannot be empty")
    return replace(project, brief=text.strip(), stage=Stage.REVIEW)


def confirm_attributes(project: ProductProject) -> ProductProject:
    if project.stage != Stage.REVIEW:
        raise ValueError("Review is not expected")
    return replace(project, attributes_confirmed=True, stage=Stage.APPROVAL)


def approve(project: ProductProject, *, quote_accepted: bool) -> ProductProject:
    if project.stage != Stage.APPROVAL or not project.attributes_confirmed:
        raise ValueError("Attributes have not been confirmed")
    if not quote_accepted:
        raise ValueError("Explicit cost acceptance required")
    return replace(project, approved=True)


def upload_message(project: ProductProject) -> str:
    count = len(project.reference_ids)
    return f"Загружено фотографий: {count}/30. Добавить ещё или продолжить?"
