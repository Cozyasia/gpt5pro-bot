"""Post-import compatibility patch for 3–7 slide topic presentations."""
from __future__ import annotations

import re
import sys
from copy import deepcopy


def _topic(text: str) -> str:
    for line in (text or "").splitlines():
        match = re.search(
            r"(?i)^(?:тема|тема презентации|название презентации|проект|тестовая\s+презентация)\s*[:—-]\s*[«\"']?([^«»\"'\n.]{2,80})",
            line.strip(),
        )
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" :—-\"'«»")
    return ""


def _count(text: str) -> int:
    match = re.search(r"(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?\s*(?:слайд|страниц)", text or "", re.I)
    if not match:
        return 12
    return max(3, min(16, max(int(match.group(1)), int(match.group(2) or match.group(1)))))


def _compact_structure(project: dict) -> list[dict]:
    profile = project.get("profile", {})
    title = profile.get("brand_name") or _topic(project.get("raw_brief", "")) or "Презентация"
    count = int(profile.get("requested_slide_count") or 3)
    cards = [
        (title, "cover", True, [profile.get("tagline") or "Краткая презентация темы"]),
        ("Ключевая идея", "split", True, ["Основной тезис из брифа", "Контекст и объяснение"]),
        ("Главные факты", "cards", False, ["Факты строго из брифа", "Без вымышленных данных"]),
        ("Вывод", "cta", True, ["Итог", "Следующий шаг или рекомендация"]),
    ]
    while len(cards) < count:
        cards.insert(-1, ("Дополнительный аспект", "split", True, ["Содержание строго по текущему брифу"]))
    selected = cards[: max(1, count - 1)] + [cards[-1]]
    return [{"title": title, "layout": layout, "image_needed": image_needed, "bullets": bullets, "image_prompt": ""} for title, layout, image_needed, bullets in selected]


def apply_short_deck_patch(mod) -> None:
    if getattr(mod, "_neyronix_short_deck_patch", False):
        return
    original_extract = mod._extract_brand_name_regex
    original_parse = mod._parse_profile
    original_fallback = mod._fallback_structure
    original_normalize = mod._normalize_structure

    def extract(text: str) -> str:
        return _topic(text) or original_extract(text)

    async def parse(raw_brief: str, update=None):
        profile = await original_parse(raw_brief, update)
        requested = _count(raw_brief)
        profile["requested_slide_count"] = requested
        title = _topic(raw_brief)
        if title:
            profile["brand_name"] = title
        return profile

    def fallback(project: dict) -> list[dict]:
        if int(project.get("profile", {}).get("requested_slide_count") or 12) < 8:
            return _compact_structure(project)
        return original_fallback(project)

    def normalize(value, fallback_slides):
        if len(fallback_slides) >= 8:
            return original_normalize(value, fallback_slides)
        if not isinstance(value, list):
            return fallback_slides
        result = []
        for item in value:
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            result.append({
                "title": str(item.get("title") or "").strip()[:160],
                "layout": str(item.get("layout") or "split").strip(),
                "image_needed": bool(item.get("image_needed")),
                "bullets": [str(v).strip()[:280] for v in (item.get("bullets") or []) if str(v).strip()][:6],
                "image_prompt": str(item.get("image_prompt") or "").strip()[:1200],
            })
        target = len(fallback_slides)
        if len(result) < target:
            return fallback_slides
        while len(result) > target:
            result.pop(-2)
        return result

    mod._extract_brand_name_regex = extract
    mod._parse_profile = parse
    mod._fallback_structure = fallback
    mod._normalize_structure = normalize
    mod._neyronix_short_deck_patch = True


def install_after_v105() -> None:
    if any(getattr(finder, "_neyronix_short_deck_marker", False) for finder in sys.meta_path):
        return
    previous = next((finder for finder in sys.meta_path if getattr(finder, "_v105_marker", False)), None)
    if previous is None:
        raise RuntimeError("Presentation v105 import hook is not installed")

    class Loader:
        def __init__(self, original):
            self.original = original

        def create_module(self, spec):
            return self.original.create_module(spec) if hasattr(self.original, "create_module") else None

        def exec_module(self, module):
            self.original.exec_module(module)
            apply_short_deck_patch(module)

    class Finder:
        _neyronix_short_deck_marker = True

        def find_spec(self, fullname, path=None, target=None):
            if fullname != "presentation_studio":
                return None
            spec = previous.find_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                spec.loader = Loader(spec.loader)
            return spec

    sys.meta_path.insert(0, Finder())
