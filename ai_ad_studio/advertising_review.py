"""Strictly curated advertising catalog: only manually approved source prompts.

An imported original is not automatically an advertising-ready template.
No synthetic prompt generation, no rewriting, and no production bot wiring.
"""
from .original_prompt_library import (
    list_all_imported_originals, get_any_imported_original,
)

REVIEW_STATUSES = frozenset({"approved", "rejected", "pending"})

def advertising_review_report(review_decisions: dict[str, str] | None = None) -> dict:
    """Apply explicit human decisions without silently approving unreviewed texts."""
    decisions = review_decisions or {}
    entries = list_all_imported_originals()
    ids = {entry["id"] for entry in entries}
    unknown = set(decisions) - ids
    if unknown:
        raise ValueError(f"Unknown source IDs in review: {sorted(unknown)}")
    invalid = {key: status for key, status in decisions.items()
               if status not in REVIEW_STATUSES}
    if invalid:
        raise ValueError(f"Invalid review decisions: {invalid}")
    approved = []
    rejected = []
    pending = []
    for entry in entries:
        status = decisions.get(entry["id"], "pending")
        target = {"approved": approved, "rejected": rejected,
                  "pending": pending}[status]
        target.append(entry["id"])
    return {
        "imported_full_text_count": len(entries),
        "approved_advertising_count": len(approved),
        "rejected_count": len(rejected),
        "pending_manual_review_count": len(pending),
        "approved_ids": tuple(approved),
        "rejected_ids": tuple(rejected),
        "pending_ids": tuple(pending),
        "ready_for_200_ad_prompts": len(approved) >= 200,
    }

def list_approved_advertising_prompts(review_decisions: dict[str, str]) -> tuple[dict, ...]:
    report = advertising_review_report(review_decisions)
    return tuple(get_any_imported_original(prompt_id)
                 for prompt_id in report["approved_ids"])
