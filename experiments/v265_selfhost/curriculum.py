"""Explicit curriculum; loss reduction alone never authorizes stage advancement."""

STAGES = {
    "A": {
        "active": [
            "neutral",
            "coefficients",
            "residual",
            "jaw",
            "chin",
            "nose",
            "mouth",
            "eyes",
            "cheeks",
            "brows",
            "orientation",
            "area",
            "edge",
            "laplacian",
            "arap_like",
            "orientation_barrier",
            "compression",
            "expansion",
            "residual_bound",
        ],
        "metrics": [
            "withheld_neutral_regional_error",
            "orientation_failures",
            "stretch_envelope",
        ],
    },
    "B": {
        "active": ["paired_identity", "landmarks", "silhouette", "depth", "visibility"],
        "metrics": ["independent_cross_view_regional_nme", "canonical_identity_drift"],
    },
    "C": {
        "active": [
            "expression_orthogonality",
            "paired_identity",
            "landmarks",
            "silhouette",
        ],
        "metrics": [
            "case08_intrinsic_mouth_error",
            "target_opening_error",
            "target_smile_error",
            "target_teeth_error",
        ],
    },
    "D": {
        "active": ["albedo"],
        "metrics": ["cross_lighting_albedo_error", "persistent_detail_retention"],
    },
    "E": {
        "active": ["parsing"],
        "metrics": [
            "glasses_frame_iou",
            "lens_iou",
            "eye_occlusion_iou",
            "case07_accessory_preservation",
        ],
    },
    "F": {
        "active": [
            "silhouette",
            "landmarks",
            "depth",
            "visibility",
            "albedo",
            "parsing",
        ],
        "metrics": [
            "case06_valid_surface",
            "full_critical_coverage",
            "public_matrix_geometry",
            "person_b_bit_exact",
            "neck_bit_exact",
        ],
    },
}


def weights_for(stage, names):
    if stage == "ENGINEERING_ALL_LOSSES":
        return {name: 1.0 for name in names}
    if stage not in STAGES:
        raise ValueError("unknown curriculum stage")
    active = set()
    for key in STAGES:
        active.update(STAGES[key]["active"])
        if key == stage:
            break
    return {name: float(name in active) for name in names}


def exit_stage(stage, metrics, calibration):
    if stage not in STAGES:
        return False
    if (
        not calibration
        or calibration.get("approved") is not True
        or calibration.get("split") != "validation"
        or not calibration.get("source_sha256")
    ):
        return False
    for name in STAGES[stage]["metrics"]:
        spec = calibration.get("limits", {}).get(name)
        if name not in metrics or spec is None:
            return False
        value = metrics[name]
        if (
            not isinstance(value, (float, int))
            or not spec["min"] <= value <= spec["max"]
        ):
            return False
    return True
