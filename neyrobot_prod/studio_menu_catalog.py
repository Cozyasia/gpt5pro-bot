"""Catalog routes aligned with verified current production modules.

This is a presentation-only mapping, not an authorization or handler registry.
Unavailable routes must remain disabled until production callback validation.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class StudioSection:
    slug: str
    title: str
    callback: str | None
    verified_source: str


SECTIONS = (
    StudioSection("market", "Маркетплейсы", "ent:brief:product_ad", "neyrobot_prod/production_briefs.py (current main commit #221)"),
    StudioSection("medicine", "AI-Медицина", None, "not yet verified in current main"),
    StudioSection("video", "AI-Видео", None, "not yet verified in current main"),
    StudioSection("realty", "Недвижимость", "revideo:start", "current main commit #221"),
    StudioSection("celebrity", "Селфи со звездой", None, "not yet verified in current main"),
    StudioSection("photo", "AI-Фотостудия", None, "not yet verified in current main"),
    StudioSection("music", "Музыка", None, "not yet verified in current main"),
    StudioSection("study", "Учёба", None, "not yet verified in current main"),
    StudioSection("work", "Работа", None, "not yet verified in current main"),
    StudioSection("assistant", "AI-Ассистент", None, "not yet verified in current main"),
    StudioSection("advert", "Реклама товара", "ent:brief:product_ad", "current main commit #221"),
)


def verified_callback(slug: str) -> str | None:
    return next((section.callback for section in SECTIONS if section.slug == slug), None)
