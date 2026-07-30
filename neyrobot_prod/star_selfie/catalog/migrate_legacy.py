"""Verified legacy catalog migration sources.

Only import characters and references found in a checked legacy file, backup
branch, persistent disk snapshot, or release archive. Never invent entries.
"""

LEGACY_SOURCES = (
    "celebrity_selfie_v122.py",
    "celebrity_selfie_v124.py",
    "ui_selfie_v138.py",
    "ui_selfie_v138_compat.py",
    "neyrobot_prod/hotfix_v160.py",
    "neyrobot_prod/hotfix_v161.py",
    "neyrobot_prod/hotfix_v162.py",
    "neyrobot_prod/v161_reference_v2.py",
    "neyrobot_prod/v162_flow_guard.py",
    "assets/celebrities/catalog.json",
    "/data/celebrity_selfie/catalog.json",
)
