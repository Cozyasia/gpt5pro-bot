"""Source-first ad studio catalog; never generate replacement prompt copy.

This adapter exposes published original prompt texts to Telegram handlers and
future UI clients without connecting payment or provider APIs.
"""
from .original_prompt_library import (
    list_all_imported_originals, get_any_imported_original,
)
from .heydreaming_verified_catalog import PROMPTS as HEYDREAMING

HEY_BY_ID = {p.id: p for p in HEYDREAMING}

def search_original_prompts(query: str = "", *, page: int = 1,
                            page_size: int = 10,
                            reviewed_only: bool = False) -> dict:
    if page < 1 or not 1 <= page_size <= 50:
        raise ValueError("Invalid page or page_size")
    q = query.strip().casefold()
    entries = list_all_imported_originals()
    matched = tuple(
        e for e in entries
        if (not reviewed_only or e.get("commercial_review") != "pending")
        and (not q or q in e["title"].casefold()
             or q in e.get("category", "").casefold()
             or any(q in tag.casefold() for tag in HEY_BY_ID[e["id"]].tags)
             if e["id"] in HEY_BY_ID
             else (not q or q in e["title"].casefold()))
    )
    start = (page - 1) * page_size
    return {
        "total": len(matched), "page": page, "page_size": page_size,
        "items": matched[start:start + page_size],
    }

def get_prompt_for_display(prompt_id: str) -> dict:
    return get_any_imported_original(prompt_id)
