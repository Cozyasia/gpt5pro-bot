"""Diagnostic identity/expression decomposition for canonical L mouth geometry.

The renderer continues to use the model's source-identity/target-expression 3D
construction.  These descriptors independently state what must be preserved;
they do not patch landmarks or tune a residual field.
"""

import numpy as np


def _points(value):
    p = np.asarray(value, dtype=np.float32)
    if p.shape != (68, 2) or not np.isfinite(p).all():
        raise ValueError("expected finite 68-point landmarks")
    iod = float(np.linalg.norm(p[36:42].mean(0) - p[42:48].mean(0)))
    if iod <= 1e-6:
        raise ValueError("degenerate eye frame")
    return p, iod


def source_mouth_identity(landmarks):
    p, iod = _points(landmarks)
    width = float(np.linalg.norm(p[54] - p[48]) / iod)
    upper = float(np.mean(np.linalg.norm(p[[50, 51, 52]] - p[[61, 62, 63]], axis=1)) / iod)
    lower = float(np.mean(np.linalg.norm(p[[56, 57, 58]] - p[[65, 66, 67]], axis=1)) / iod)
    nose_width = float(np.linalg.norm(p[35] - p[31]) / iod)
    philtrum = float(np.linalg.norm(p[51] - p[33]) / iod)
    chin = float(np.linalg.norm(p[8] - p[57]) / iod)
    cupid = float((0.5 * (p[50, 1] + p[52, 1]) - p[51, 1]) / iod)
    return {
        "mouth_width": width,
        "upper_lip_thickness": upper,
        "lower_lip_thickness": lower,
        "lip_thickness_ratio": upper / max(lower, 1e-8),
        "cupid_bow": cupid,
        "philtrum": philtrum,
        "mouth_to_nose_ratio": width / max(nose_width, 1e-8),
        "mouth_to_chin_ratio": width / max(chin, 1e-8),
    }


def target_mouth_expression(landmarks):
    p, iod = _points(landmarks)
    centre = 0.5 * (p[62] + p[66])
    corners = p[[48, 54]]
    return {
        "opening": float(np.linalg.norm(p[62] - p[66]) / iod),
        "smile_amount": float((centre[1] - corners[:, 1].mean()) / iod),
        "corner_elevation_left": float((centre[1] - p[48, 1]) / iod),
        "corner_elevation_right": float((centre[1] - p[54, 1]) / iod),
        "stretch": float(np.linalg.norm(p[54] - p[48]) / iod),
        "teeth_visibility_proxy": float(
            max(0.0, np.linalg.norm(p[62] - p[66]) - np.linalg.norm(p[51] - p[62])) / iod
        ),
        "bounded_asymmetry": float(abs(p[48, 1] - p[54, 1]) / iod),
    }


def mouth_decomposition_report(source, target, final):
    source_identity = source_mouth_identity(source)
    target_expression = target_mouth_expression(target)
    final_identity = source_mouth_identity(final)
    final_expression = target_mouth_expression(final)
    identity_error = {
        k: abs(final_identity[k] - value) for k, value in source_identity.items()
    }
    expression_error = {
        k: abs(final_expression[k] - value) for k, value in target_expression.items()
    }
    # Engineering reporting bounds only; not fitted acceptance calibration.
    identity_within = max(identity_error.values()) <= 0.08
    expression_within = max(
        expression_error[k]
        for k in (
            "opening",
            "smile_amount",
            "corner_elevation_left",
            "corner_elevation_right",
            "bounded_asymmetry",
        )
    ) <= 0.05
    return {
        "source_intrinsic": source_identity,
        "target_expression": target_expression,
        "final_intrinsic": final_identity,
        "final_expression": final_expression,
        "identity_absolute_error": identity_error,
        "expression_absolute_error": expression_error,
        "identity_geometry_within_engineering_bound": bool(identity_within),
        "target_expression_within_engineering_bound": bool(expression_within),
        "teeth_visibility_is_geometry_proxy_not_appearance_proof": True,
        "mouth_texture_expression_compatible": False,
        "expression_disentangled": False,
    }
