"""Read-only catalog for original licensed professional advertising prompts.

Unlike the legacy generated catalog, this module serves verbatim published
prompt texts and explicit attribution. No AI rewriting or synthetic expansion.
"""
from .heydreaming_verified_catalog import PROMPTS as HEYDREAMING_ENTRIES
from .heydreaming_original_prompts import ORIGINAL_PROMPTS, SOURCE_REPOSITORY, LICENSE, ATTRIBUTION
from .seedance25_original_prompts import ORIGINAL_PROMPTS as SEEDANCE25_PROMPTS, SOURCE as SEEDANCE25_SOURCE, RIGHTS_NOTE as SEEDANCE25_RIGHTS
from .seedance25_additional_source_prompts import ORIGINAL_PROMPTS as SEEDANCE25_ADDITIONAL

from .callirra_batch01 import ORIGINAL_PROMPTS as CALLIRRA_01
from .callirra_batch02 import ORIGINAL_PROMPTS as CALLIRRA_02
from .callirra_batch03 import ORIGINAL_PROMPTS as CALLIRRA_03
from .callirra_batch04 import ORIGINAL_PROMPTS as CALLIRRA_04
from .callirra_batch05 import ORIGINAL_PROMPTS as CALLIRRA_05
from .callirra_batch06 import ORIGINAL_PROMPTS as CALLIRRA_06
from .callirra_batch07 import ORIGINAL_PROMPTS as CALLIRRA_07

from .h3_advertising_source_prompts import ORIGINAL_PROMPTS as H3_AD_PROMPTS

CALLIRRA_PROMPTS = {}
for _batch in (CALLIRRA_01, CALLIRRA_02, CALLIRRA_03, CALLIRRA_04,
               CALLIRRA_05, CALLIRRA_06, CALLIRRA_07):
    for _id, _record in _batch.items():
        if _id in CALLIRRA_PROMPTS:
            raise ValueError(f"Duplicate Callirra prompt id: {_id}")
        CALLIRRA_PROMPTS[_id] = _record

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
    """All imported full texts, including pending-review Callirra originals."""
    existing = list_full_source_prompts()
    additional = tuple({
        "id": key, "title": value["title"], "source_url": SEEDANCE25_SOURCE,
        "full_prompt_available": True, "commercial_review": "pending",
    } for key, value in SEEDANCE25_ADDITIONAL.items())
    callirra = tuple({
        "id": key, "title": value["title"], "source_url": value["source_url"],
        "full_prompt_available": True, "commercial_review": "pending",
        "publisher": "Callirra AI", "license": "CC BY 4.0",
    } for key, value in CALLIRRA_PROMPTS.items())
    h3 = tuple({
        "id": key, "title": value["title"], "source_url": value["source_url"],
        "full_prompt_available": True, "commercial_review": "pending",
        "publisher": "Flaq AI", "license": "MIT",
    } for key, value in H3_AD_PROMPTS.items())
    return existing + additional + callirra + h3


def get_any_imported_original(prompt_id: str) -> dict:
    if prompt_id in H3_AD_PROMPTS:
        return {"id": prompt_id, **H3_AD_PROMPTS[prompt_id],
                "publisher": "Flaq AI", "license": "MIT"}
    if prompt_id in CALLIRRA_PROMPTS:
        return {"id": prompt_id, **CALLIRRA_PROMPTS[prompt_id],
                "publisher": "Callirra AI", "license": "CC BY 4.0"}
    if prompt_id in SEEDANCE25_ADDITIONAL:
        record = SEEDANCE25_ADDITIONAL[prompt_id]
        return {"id": prompt_id, "title": record["title"], "prompt": record["prompt"],
                "source_url": SEEDANCE25_SOURCE, "commercial_review": "pending"}
    return get_full_source_prompt(prompt_id)
