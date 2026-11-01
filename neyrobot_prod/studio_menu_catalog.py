"""Catalog routes aligned with handlers verified in the current application.

This is a presentation-only mapping, not an authorization or handler registry.
The callback names are intentionally kept internal to the Telegram application;
the Mini App only ever receives the stable, allow-listed ``slug`` values.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class StudioSection:
    slug: str
    title: str
    callback: str | None
    verified_source: str


SECTIONS = (
    StudioSection("market", "Маркетплейсы", "ent:brief:product_ad", "current main: ent:brief:product_ad callback"),
    StudioSection("medicine", "AI-Медицина", "mode:medicine", "current main: on_mode_cb"),
    StudioSection("video", "AI-Видео", "act:fun:textvideo", "current main: on_mode_cb"),
    StudioSection("realty", "Недвижимость", "revideo:start", "current main commit #221"),
    StudioSection("celebrity", "Селфи со звездой", "fun:aiselfie", "current main: AI-selfie high-priority handler"),
    StudioSection("photo", "AI-Фотостудия", "engine:images", "current main: engine callback handler"),
    StudioSection("music", "Музыка", "fun:music", "current main: on_cb_fun"),
    StudioSection("study", "Учёба", "mode:study", "current main: on_mode_cb"),
    StudioSection("work", "Работа", "mode:work", "current main: on_mode_cb"),
    StudioSection("assistant", "AI-Ассистент", "mode:root", "current main: on_mode_cb"),
    StudioSection("advert", "Реклама товара", "ent:brief:product_ad", "current main commit #221"),
)


def verified_callback(slug: str) -> str | None:
    return next((section.callback for section in SECTIONS if section.slug == slug), None)


def verified_section(slug: str) -> StudioSection | None:
    """Return catalog metadata only when the section has a verified callback."""
    return next(
        (section for section in SECTIONS if section.slug == slug and section.callback),
        None,
    )
