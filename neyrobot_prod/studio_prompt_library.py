"""Read-only Studio prompt template catalog.

Templates are editable suggestions; no provider call, charging or menu change.
"""
from __future__ import annotations

import json
from pathlib import Path

_CATALOG = Path(__file__).with_name("studio_prompt_library.json")


def list_prompt_categories() -> tuple[dict, ...]:
    templates = _load()
    categories = {}
    for item in templates:
        categories.setdefault(item["category"], {"id": item["category"], "title": item["category_label"], "count": 0})
        categories[item["category"]]["count"] += 1
    return tuple(categories.values())


def list_prompt_templates(category: str | None = None) -> tuple[dict, ...]:
    templates = _load()
    if category is not None:
        templates = [item for item in templates if item["category"] == category]
    return tuple(dict(item) for item in templates)


def get_prompt_template(template_id: str) -> dict | None:
    for item in _load():
        if item["id"] == template_id:
            return dict(item)
    return None


def _load() -> list[dict]:
    payload = json.loads(_CATALOG.read_text(encoding="utf-8"))
    items = payload["templates"]
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Studio prompt IDs")
    return items
