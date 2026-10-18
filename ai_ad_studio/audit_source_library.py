"""Audit imported prompt corpus before counting it as commercially ready.

Usage: python -m ai_ad_studio.audit_source_library
This audit does not modify any original prompt or deploy any bot changes.
"""
from collections import Counter
from difflib import SequenceMatcher
import json
import re

from .original_prompt_library import list_all_imported_originals, get_any_imported_original

COMMERCIAL_HINTS = re.compile(
    r"\b(ad|advert|commercial|product|brand|marketing|fashion|"
    r"showcase|packaging|cosmetic|skincare|perfume|watch|jewelry|"
    r"restaurant|hotel|real estate|retail|ugc|unboxing|launch)\b",
    re.I,
)

def audit() -> dict:
    entries = list_all_imported_originals()
    ids = [entry["id"] for entry in entries]
    records = [get_any_imported_original(i) for i in ids]
    normalized = [
        re.sub(r"\s+", " ", rec["prompt"]).strip().casefold()
        for rec in records
    ]
    exact_groups = {}
    for identifier, body in zip(ids, normalized):
        exact_groups.setdefault(body, []).append(identifier)
    duplicates = [group for group in exact_groups.values() if len(group) > 1]
    near = []
    # Compare only same-source length-near text to avoid expensive quadratic
    # similarity scans over dissimilar source material.
    for i, left in enumerate(normalized):
        for j in range(i + 1, len(normalized)):
            right = normalized[j]
            if not left or not right or min(len(left), len(right)) / max(len(left), len(right)) < .85:
                continue
            if SequenceMatcher(None, left, right, autojunk=True).ratio() >= .90:
                near.append([ids[i], ids[j]])
    candidates = [
        rec["id"] for rec in records
        if not COMMERCIAL_HINTS.search(rec["title"] + " " + rec["prompt"][:250])
    ]
    review_pending = [
        rec["id"] for rec in records
        if rec.get("commercial_review") == "pending"
    ]
    return {
        "full_text_count": len(records),
        "source_counts": dict(Counter(rec["source_url"] for rec in records)),
        "duplicate_ids": sorted(i for i, n in Counter(ids).items() if n > 1),
        "exact_duplicate_text_groups": duplicates,
        "near_duplicate_pairs": near,
        "commercial_suitability_manual_review_candidates": candidates,
        "commercial_review_pending": review_pending,
        "note": "Heuristic classification only; source rights and ad suitability require human verification.",
    }

if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
