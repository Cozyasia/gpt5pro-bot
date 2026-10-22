"""Telegram-ready prompt catalog pagination and callback parsing.

No bot handler registration or provider invocation occurs in this module.
"""
from __future__ import annotations

from neyrobot_prod.studio_prompt_library import (
    get_prompt_template, list_prompt_categories, list_prompt_templates,
)

PAGE_SIZE = 5
PREFIX = "spl"


def category_buttons() -> tuple[tuple[str, str], ...]:
    return tuple((f'{c["title"]} ({c["count"]})', f'{PREFIX}:c:{c["id"]}:0')
                 for c in list_prompt_categories())


def template_page(category: str, page: int = 0) -> dict:
    if not isinstance(page, int) or page < 0:
        raise ValueError("Invalid page")
    categories = {c["id"] for c in list_prompt_categories()}
    if category not in categories:
        raise ValueError("Unknown category")
    items = list_prompt_templates(category)
    start = page * PAGE_SIZE
    if start >= len(items):
        raise ValueError("Page out of range")
    return {
        "category": category, "page": page, "total": len(items),
        "buttons": tuple((item["title"], f'{PREFIX}:p:{item["id"]}') for item in items[start:start + PAGE_SIZE]),
        "previous": f"{PREFIX}:c:{category}:{page - 1}" if page > 0 else None,
        "next": f"{PREFIX}:c:{category}:{page + 1}" if start + PAGE_SIZE < len(items) else None,
    }


def resolve_template_callback(data: str) -> dict | None:
    if not isinstance(data, str) or not data.startswith(f"{PREFIX}:p:"):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        return None
    return get_prompt_template(parts[2])
