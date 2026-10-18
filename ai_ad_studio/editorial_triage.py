"""Editorial title-based triage of imported prompt source records.

Preliminary classification only. Commercial approval still requires
individual inspection of complete source text and usage rights.
"""
from .original_prompt_library import list_all_imported_originals

NON_AD_S25 = {1,2,3,4,5,6,7,8,9,10,28,29,53,54,55,56,57,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,99}
NON_AD_CALL = {4,6,9,11,12,15,16,19,20,21,24,72,73,74,75,78,81,83,85,86,87,88,89,90,92,93,95,97,99,100,159}
BROLL_S25 = {30,51,52,58,91,93,94,95,96,97,98,100}
BROLL_CALL = {149,150,151,152,153,154,155,156,158}

def preliminary_report():
    entries = list_all_imported_originals()
    ids = {e["id"] for e in entries}
    excluded = ({f"S25-{i}" for i in NON_AD_S25} |
                {f"CALL-{i:03d}" for i in NON_AD_CALL}) & ids
    broll = ({f"S25-{i}" for i in BROLL_S25} |
             {f"CALL-{i:03d}" for i in BROLL_CALL}) & ids
    possible = ids - excluded - broll
    return {
        "imported": len(ids),
        "excluded_non_ad": len(excluded),
        "supporting_broll_only": len(broll),
        "possible_ad_candidates": len(possible),
        "minimum_replacements_for_200": max(0, 200-len(possible)),
        "excluded_ids": sorted(excluded),
        "broll_ids": sorted(broll),
        "approval_status": "pending_full_text_review",
    }
