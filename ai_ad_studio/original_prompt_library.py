"""Read-only catalog for original licensed professional advertising prompts.

Unlike the legacy generated catalog, this module serves verbatim published
prompt texts and explicit attribution. No AI rewriting or synthetic expansion.
"""
from .heydreaming_verified_catalog import PROMPTS as HEYDREAMING_ENTRIES
from .heydreaming_original_prompts import ORIGINAL_PROMPTS, SOURCE_REPOSITORY, LICENSE, ATTRIBUTION
from .seedance25_original_prompts import ORIGINAL_PROMPTS as SEEDANCE25_PROMPTS, SOURCE as SEEDANCE25_SOURCE, RIGHTS_NOTE as SEEDANCE25_RIGHTS
from .seedance25_additional_source_prompts import ORIGINAL_PROMPTS as SEEDANCE25_ADDITIONAL

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


def list_full_source_prompts() -> tuple[dict, ...]:
    """Return all 100 imported full-text source records (52 + 48)."""
    first = list_original_professional_prompts()
    second = tuple({
        "id": prompt_id, "title": record["title"],
        "source_url": SEEDANCE25_SOURCE, "publisher": "incendies / imageat.com",
        "rights_note": SEEDANCE25_RIGHTS, "full_prompt_available": True,
    } for prompt_id, record in SEEDANCE25_PROMPTS.items())
    return first + second


def get_full_source_prompt(prompt_id: str) -> dict:
    """Return the unmodified original prompt and its source information."""
    if prompt_id in SEEDANCE25_PROMPTS:
        record = SEEDANCE25_PROMPTS[prompt_id]
        return {"id": prompt_id, "title": record["title"], "prompt": record["prompt"],
                "source_url": SEEDANCE25_SOURCE, "publisher": "incendies / imageat.com",
                "rights_note": SEEDANCE25_RIGHTS}
    return get_original_professional_prompt(prompt_id)


def list_all_imported_originals() -> tuple[dict, ...]:
    """152 full texts, with 52 new entries awaiting commercial suitability review."""
    existing = list_full_source_prompts()
    additional = tuple({
        "id": key, "title": value["title"], "source_url": SEEDANCE25_SOURCE,
        "full_prompt_available": True, "commercial_review": "pending",
    } for key, value in SEEDANCE25_ADDITIONAL.items())
    return existing + additional


def get_any_imported_original(prompt_id: str) -> dict:
    if prompt_id in SEEDANCE25_ADDITIONAL:
        record = SEEDANCE25_ADDITIONAL[prompt_id]
        return {"id": prompt_id, "title": record["title"], "prompt": record["prompt"],
                "source_url": SEEDANCE25_SOURCE, "commercial_review": "pending"}
    return get_full_source_prompt(prompt_id)
