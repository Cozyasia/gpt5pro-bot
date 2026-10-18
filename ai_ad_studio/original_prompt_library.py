"""Read-only catalog for original licensed professional advertising prompts.

Unlike the legacy generated catalog, this module serves verbatim published
prompt texts and explicit attribution. No AI rewriting or synthetic expansion.
"""
from .heydreaming_verified_catalog import PROMPTS as HEYDREAMING_ENTRIES
from .heydreaming_original_prompts import ORIGINAL_PROMPTS, SOURCE_REPOSITORY, LICENSE, ATTRIBUTION

def list_original_professional_prompts(category: str | None = None) -> tuple[dict, ...]:
    return tuple(
        {"id": entry.id, "title": entry.title, "category": entry.category,
         "duration": entry.duration, "aspect": entry.aspect, "source_url": entry.source_url,
         "publisher": ATTRIBUTION, "license": LICENSE, "full_prompt_available": True}
        for entry in HEYDREAMING_ENTRIES
        if category is None or entry.category == category
    )

def get_original_professional_prompt(prompt_id: str) -> dict:
    entry = next((p for p in HEYDREAMING_ENTRIES if p.id == prompt_id), None)
    if entry is None:
        raise KeyError(f"Unknown professional prompt: {prompt_id}")
    return {
        "id": entry.id, "title": entry.title, "category": entry.category,
        "duration": entry.duration, "aspect": entry.aspect,
        "prompt": ORIGINAL_PROMPTS[entry.id], "source_url": entry.source_url,
        "source_repository": SOURCE_REPOSITORY, "publisher": ATTRIBUTION,
        "license": LICENSE, "adaptation_required": True,
    }
