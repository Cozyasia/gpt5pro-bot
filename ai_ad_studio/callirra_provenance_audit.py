"""Provenance gate for the 52 imported Callirra source originals.

Source comparison performed against Callirra's README.md and ATTRIBUTION.md.
The latter lists community/ cases; imported IDs are from cases/ and are
not in that community attribution list as checked on 2026-10-19.
This establishes publisher provenance, NOT verified ad suitability.
"""
from .original_prompt_library import CALLIRRA_PROMPTS

EXPECTED_CALLIRRA_CASES = frozenset({
    4, 6, 9, 11, 12, 15, 16, 19, 20, 21, 24,
    28, 29, 30, 33, 34, 35, 40, 44, 45, 46, 47,
    72, 73, 74, 75, 78, 81, 83, 85, 86, 87, 88, 89,
    90, 92, 93, 95, 97, 99, 100, 147, 149, 150, 151,
    152, 153, 154, 155, 156, 158, 159,
})
ATTRIBUTION_SOURCE = "https://github.com/callirra-ai/seedance-2-5-prompt-atlas/blob/main/ATTRIBUTION.md"
LICENSE_SOURCE = "https://github.com/callirra-ai/seedance-2-5-prompt-atlas"

def check_callirra_provenance() -> dict:
    actual = frozenset(int(key.split("-")[1]) for key in CALLIRRA_PROMPTS)
    wrong_urls = [
        key for key, record in CALLIRRA_PROMPTS.items()
        if f"/cases/{int(key.split('-')[1]):03d}-" not in record["source_url"]
    ]
    return {
        "imported_count": len(CALLIRRA_PROMPTS),
        "expected_count": len(EXPECTED_CALLIRRA_CASES),
        "missing_case_numbers": sorted(EXPECTED_CALLIRRA_CASES - actual),
        "unexpected_case_numbers": sorted(actual - EXPECTED_CALLIRRA_CASES),
        "invalid_source_urls": wrong_urls,
        "community_cases_in_import": [],
        "source_licence_claim": "CC BY 4.0",
        "commercial_suitability_verified": False,
        "passed": actual == EXPECTED_CALLIRRA_CASES and not wrong_urls,
    }
