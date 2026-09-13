"""Synthetic engineering thresholds, never real-photo acceptance."""

import math


def qualify(report, controlled, stress):
    # Explicit validation policy v1. Missing evidence is failure, not default PASS.
    checks = dict(
        trained=report.get("epochs", 0) > 0,
        reconstruction=report.get("relative_to_mean", math.inf) < 0.8,
        expression_invariance=controlled.get("identity_drift_mm", {}).get(
            "smile", math.inf
        )
        < 0.5,
        pose_invariance=controlled.get("identity_drift_mm", {}).get("yaw", math.inf)
        < 0.5,
        lighting_invariance=controlled.get("albedo_drift_mse", {}).get(
            "light", math.inf
        )
        < 0.002,
        geometry=report.get("orientation_failures", -1) == 0
        and all(r.get("orientation_failures", -1) == 0 for r in stress),
        case06_full_surface=all(r.get("case06_pass") is True for r in stress),
        case08_intrinsic=controlled.get("case08_pass") is True,
        accessory=controlled.get("case07_pass") is True,
        deterministic=report.get("deterministic") is True,
        onnx=report.get("onnx_max_abs_error", math.inf) < 1e-4,
    )
    return dict(
        checks=checks,
        v0=all(checks.values()),
        real_human_quality_proven=False,
        production_ready=False,
    )
