"""Machine prequalification only. Missing evidence fails closed."""

import numpy as np

VERSION = "selfhost-quality-1"
REQUIRED = [
    "source_morphology",
    "cross_view_identity",
    "expression_agreement",
    "geometry_validity",
    "visibility_complete",
    "accessory_preserved",
    "appearance_consistent",
]


def qualify(evidence, model_manifest):
    missing = [k for k in REQUIRED if evidence.get(k) is not True]
    if not model_manifest.get("commercial_training_allowed"):
        missing.append("commercial_data_rights")
    if model_manifest.get("mock_only", True):
        missing.append("real_identity_weights")
    if not model_manifest.get("identity_quality_qualified", False):
        missing.append("identity_validation")
    return {
        "machine_prequalified": not missing,
        "failed_or_missing": missing,
        "human_visual_review_required": True,
        "delivery_allowed": False,
        "gate_version": VERSION,
    }
