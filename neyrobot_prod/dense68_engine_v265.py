# -*- coding: utf-8 -*-
"""Pure V265 dense68 PERSON-A transfer engine.

This module is deliberately not a runtime overlay and does not install handlers,
replace older enforcers, call external FaceSwap providers, or fall back to an older
selfie implementation. It contains only the final local image algorithm used by the
V265 single production owner:

* YuNet selects source and target faces and establishes one similarity transform.
* PIPNet 68 landmarks own local identity geometry inside PERSON-A ROI.
* all float/LAB/deformation work stays inside the compact left-person ROI.
* the strict candidate gets one bounded deep identity-core refinement.
* source eye texture is restored through the same global+dense68 deformation field.
* PERSON-B is pixel locked.
* any algorithm/model/preflight failure raises; there is no alternate algorithm.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v263_dense_identity_lock as v263

VERSION = "v265-dense68-single-owner-production-2026-09-01"

_REFINEMENT_LARGE_FACE_MIN = 500.0
_REFINEMENT_MEDIUM_FACE_MIN = 360.0
_REFINEMENT_LARGE_IDENTITY = 0.825
_REFINEMENT_MEDIUM_IDENTITY = 0.790
_REFINEMENT_LARGE_EYE_ERROR = 0.032
_REFINEMENT_LARGE_INTEROCULAR = 0.030
_REFINEMENT_LARGE_EYE_ASYMMETRY = 0.008
_REFINEMENT_LARGE_INNER_NME = 0.040
_REFINEMENT_MEDIUM_EYE_ERROR = 0.045
_REFINEMENT_MEDIUM_INTEROCULAR = 0.040
_REFINEMENT_MEDIUM_EYE_ASYMMETRY = 0.020
_REFINEMENT_MEDIUM_INNER_NME = 0.055

_IDENTITY_GAIN_MIN = 0.012
_IDENTITY_GEOMETRY_LOSS_MAX = 0.020

_CORE_LARGE_FACE_MIN = 500.0
_CORE_LOW_STRENGTH_LARGE = 0.52
_CORE_LOW_STRENGTH_MEDIUM = 0.44
_CORE_PIXEL_MIX_LARGE = 0.10
_CORE_PIXEL_MIX_MEDIUM = 0.08
_CORE_DELTA_LIMIT = 34.0
_CORE_SIGMA_FRACTION = 0.014
_CORE_SIGMA_MIN = 5.0
_CORE_SIGMA_MAX = 11.0
_CORE_BOUNDARY_START = 0.55
_CORE_BOUNDARY_SPAN = 1.75

_OCULAR_ALPHA = 0.92
_OCULAR_MARGIN_FRACTION = 0.20
_OCULAR_FEATHER_FRACTION = 0.075
_OCULAR_MIN_MARGIN = 4
_OCULAR_MAX_MARGIN = 16
_OCULAR_MIN_FEATHER = 1.5
_OCULAR_MAX_FEATHER = 5.0


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _project_points(matrix, points):
    import numpy as np

    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    ones = np.ones((pts.shape[0], 1), dtype=np.float32)
    hom = np.concatenate([pts, ones], axis=1)
    return hom @ np.asarray(matrix, dtype=np.float32).T


def _smoothstep01(values):
    import numpy as np

    t = np.clip(values, 0.0, 1.0).astype(np.float32, copy=False)
    return t * t * (3.0 - 2.0 * t)


def _landmark_anatomy_mask(shape, bbox, landmarks, firewall_x: int):
    """Inner-face anatomical hull. No ellipse, neck, hair or full-head source mask."""
    import cv2
    import numpy as np

    h, w = int(shape[0]), int(shape[1])
    x, y, fw, fh = [float(v) for v in bbox]
    pts = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
    eyes = pts[0:2][np.argsort(pts[0:2, 0])]
    mouths = pts[3:5][np.argsort(pts[3:5, 0])]
    left_eye, right_eye = eyes[0], eyes[1]
    nose = pts[2]
    left_mouth, right_mouth = mouths[0], mouths[1]
    eye_mid = (left_eye + right_eye) * 0.5
    mouth_mid = (left_mouth + right_mouth) * 0.5

    top_y = max(y + fh * 0.12, float(min(left_eye[1], right_eye[1])) - fh * 0.18)
    bottom_y = min(y + fh * 0.84, float(mouth_mid[1]) + fh * 0.10)
    cheek_y = float(nose[1]) + 0.48 * (float(mouth_mid[1]) - float(nose[1]))
    left_side_x = max(x + fw * 0.13, min(float(left_eye[0]), float(left_mouth[0])) - fw * 0.09)
    right_side_x = min(x + fw * 0.87, max(float(right_eye[0]), float(right_mouth[0])) + fw * 0.09)
    top_left_x = max(x + fw * 0.20, float(left_eye[0]) - fw * 0.055)
    top_right_x = min(x + fw * 0.80, float(right_eye[0]) + fw * 0.055)

    polygon = np.asarray(
        [
            [top_left_x, top_y],
            [float(eye_mid[0]), max(y + fh * 0.095, top_y - fh * 0.035)],
            [top_right_x, top_y],
            [right_side_x, cheek_y],
            [min(x + fw * 0.84, float(right_mouth[0]) + fw * 0.07), float(right_mouth[1])],
            [float(mouth_mid[0]), bottom_y],
            [max(x + fw * 0.16, float(left_mouth[0]) - fw * 0.07), float(left_mouth[1])],
            [left_side_x, cheek_y],
        ],
        dtype=np.float32,
    )
    polygon[:, 0] = np.clip(polygon[:, 0], 0.0, float(max(0, firewall_x - 1)))
    polygon[:, 1] = np.clip(polygon[:, 1], 0.0, float(max(0, h - 1)))
    hull = cv2.convexHull(np.round(polygon).astype(np.int32))
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255, lineType=cv2.LINE_AA)
    mask[:, max(0, min(w, int(firewall_x))):] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)


def _mask_box(mask, *, pad: int, firewall_x: int):
    import numpy as np

    h, _ = mask.shape[:2]
    ys, xs = np.where(mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V265 anatomical landmark mask is empty")
    x0 = max(0, int(xs.min()) - int(pad))
    y0 = max(0, int(ys.min()) - int(pad))
    x1 = min(int(firewall_x), int(xs.max()) + int(pad) + 1)
    y1 = min(int(h), int(ys.max()) + int(pad) + 1)
    if x1 - x0 < 120 or y1 - y0 < 140:
        raise RuntimeError(f"V265 anatomical ROI too small: {x1-x0}x{y1-y0}")
    return x0, y0, x1, y1


def visual_refinement_reasons(metrics: dict[str, float]) -> list[str]:
    face_short = float(metrics.get("target_face_short", 0.0) or 0.0)
    if face_short < _REFINEMENT_MEDIUM_FACE_MIN:
        return []
    if face_short >= _REFINEMENT_LARGE_FACE_MIN:
        identity_limit = _REFINEMENT_LARGE_IDENTITY
        eye_limit = _REFINEMENT_LARGE_EYE_ERROR
        interocular_limit = _REFINEMENT_LARGE_INTEROCULAR
        asym_limit = _REFINEMENT_LARGE_EYE_ASYMMETRY
        inner_limit = _REFINEMENT_LARGE_INNER_NME
    else:
        identity_limit = _REFINEMENT_MEDIUM_IDENTITY
        eye_limit = _REFINEMENT_MEDIUM_EYE_ERROR
        interocular_limit = _REFINEMENT_MEDIUM_INTEROCULAR
        asym_limit = _REFINEMENT_MEDIUM_EYE_ASYMMETRY
        inner_limit = _REFINEMENT_MEDIUM_INNER_NME

    reasons: list[str] = []
    identity = float(metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    if identity < identity_limit:
        reasons.append(f"identity={identity:.4f}<{identity_limit:.4f}")
    worst_eye = max(
        float(metrics.get("left_eye_error", 0.0) or 0.0),
        float(metrics.get("right_eye_error", 0.0) or 0.0),
    )
    if worst_eye > eye_limit:
        reasons.append(f"eye_error={worst_eye:.4f}>{eye_limit:.4f}")
    interocular = float(metrics.get("interocular_ratio_delta", 0.0) or 0.0)
    if interocular > interocular_limit:
        reasons.append(f"interocular={interocular:.4f}>{interocular_limit:.4f}")
    asymmetry = float(metrics.get("eye_asymmetry_delta", 0.0) or 0.0)
    if asymmetry > asym_limit:
        reasons.append(f"eye_asymmetry={asymmetry:.4f}>{asym_limit:.4f}")
    inner_nme = float(metrics.get("inner_face_landmark_nme", 0.0) or 0.0)
    if inner_nme > inner_limit:
        reasons.append(f"inner_nme={inner_nme:.4f}>{inner_limit:.4f}")
    return reasons


def visual_quality_score(metrics: dict[str, float]) -> float:
    identity = float(metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    worst_eye = max(
        float(metrics.get("left_eye_error", 1.0) or 1.0),
        float(metrics.get("right_eye_error", 1.0) or 1.0),
    )
    interocular = float(metrics.get("interocular_ratio_delta", 1.0) or 1.0)
    inner_nme = float(metrics.get("inner_face_landmark_nme", 1.0) or 1.0)
    asymmetry = float(metrics.get("eye_asymmetry_delta", 1.0) or 1.0)
    axis = float(metrics.get("nose_mouth_axis_delta", 1.0) or 1.0)
    return identity - 2.8 * worst_eye - 1.8 * interocular - inner_nme - 0.6 * asymmetry - 0.5 * axis


def strict_geometry_safe(standard: dict[str, float], strict: dict[str, float]) -> bool:
    se = max(float(standard.get("left_eye_error", 1.0)), float(standard.get("right_eye_error", 1.0)))
    xe = max(float(strict.get("left_eye_error", 1.0)), float(strict.get("right_eye_error", 1.0)))
    si = float(standard.get("interocular_ratio_delta", 1.0))
    xi = float(strict.get("interocular_ratio_delta", 1.0))
    sn = float(standard.get("inner_face_landmark_nme", 1.0))
    xn = float(strict.get("inner_face_landmark_nme", 1.0))
    sa = float(standard.get("nose_mouth_axis_delta", 1.0))
    xa = float(strict.get("nose_mouth_axis_delta", 1.0))
    return (
        xe <= max(0.050, se + 0.012)
        and xi <= max(0.045, si + 0.012)
        and xn <= max(0.050, sn + 0.014)
        and xa <= max(0.050, sa + 0.014)
    )


def prefer_strict_refinement(standard: dict[str, float], strict: dict[str, float]) -> bool:
    sid = float(standard.get("identity_similarity_cosine", 0.0) or 0.0)
    xid = float(strict.get("identity_similarity_cosine", 0.0) or 0.0)
    if xid >= sid + _IDENTITY_GAIN_MIN:
        return strict_geometry_safe(standard, strict)
    return (
        visual_quality_score(strict) >= visual_quality_score(standard) + 0.005
        and xid >= sid - _IDENTITY_GEOMETRY_LOSS_MAX
        and strict_geometry_safe(standard, strict)
    )


def _colour_match_lab_roi_only(source_roi, target_roi, mask_roi):
    import cv2
    import numpy as np

    region = mask_roi > 80
    if int(region.sum()) < 500:
        raise RuntimeError("V265 LAB colour region too small")
    src_lab = cv2.cvtColor(source_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt_lab = cv2.cvtColor(target_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    out_lab = src_lab.copy()
    for channel in range(3):
        src_values = src_lab[:, :, channel][region]
        tgt_values = tgt_lab[:, :, channel][region]
        src_mean, tgt_mean = float(src_values.mean()), float(tgt_values.mean())
        src_std, tgt_std = float(src_values.std()), float(tgt_values.std())
        gain = 1.0 if src_std < 1.0 else max(0.78, min(1.22, tgt_std / src_std))
        out_lab[:, :, channel] = np.clip(
            (src_lab[:, :, channel] - src_mean) * gain + tgt_mean,
            0.0,
            255.0,
        )
    return cv2.cvtColor(out_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def _warp_source_direct_to_roi(source_im, matrix, box):
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    local_matrix = np.asarray(matrix, dtype=np.float32).copy()
    local_matrix[0, 2] -= float(x0)
    local_matrix[1, 2] -= float(y0)
    return cv2.warpAffine(
        source_im,
        local_matrix,
        (int(x1 - x0), int(y1 - y0)),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _dense_deform_local_roi(warped_roi, projected_dense, desired_dense, box, face_min: float):
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    roi_w, roi_h = int(x1 - x0), int(y1 - y0)
    if warped_roi.shape[1] != roi_w or warped_roi.shape[0] != roi_h:
        raise RuntimeError(
            f"V265 warped ROI shape mismatch: got={warped_roi.shape[1]}x{warped_roi.shape[0]} expected={roi_w}x{roi_h}"
        )
    sigma = max(v263._DENSE_SIGMA_MIN, min(v263._DENSE_SIGMA_MAX, float(face_min) * v263._DENSE_SIGMA_FRACTION))
    origin = np.asarray([float(x0), float(y0)], dtype=np.float32)
    projected = np.asarray(projected_dense, dtype=np.float32).reshape(v263._DENSE_COUNT, 2) - origin
    desired = np.asarray(desired_dense, dtype=np.float32).reshape(v263._DENSE_COUNT, 2) - origin
    residuals = desired - projected
    gx = np.arange(roi_w, dtype=np.float32)[None, :]
    gy = np.arange(roi_h, dtype=np.float32)[:, None]
    sum_w = np.zeros((roi_h, roi_w), dtype=np.float32)
    sum_dx = np.zeros((roi_h, roi_w), dtype=np.float32)
    sum_dy = np.zeros((roi_h, roi_w), dtype=np.float32)
    for idx in range(v263._DENSE_COUNT):
        cx, cy = float(desired[idx, 0]), float(desired[idx, 1])
        dx = (gx - cx) / max(1.0, sigma)
        dy = (gy - cy) / max(1.0, sigma)
        weight = np.exp(-0.5 * (dx * dx + dy * dy)).astype(np.float32, copy=False)
        sum_w += weight
        sum_dx += weight * float(residuals[idx, 0])
        sum_dy += weight * float(residuals[idx, 1])
    inv = 1.0 / np.maximum(sum_w, 1.0e-6)
    support = np.clip(sum_w, 0.0, 1.0)
    map_x = np.broadcast_to(gx, (roi_h, roi_w)).copy() - sum_dx * inv * support
    map_y = np.broadcast_to(gy, (roi_h, roi_w)).copy() - sum_dy * inv * support
    corrected = cv2.remap(
        warped_roi,
        map_x,
        map_y,
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return corrected, sigma, residuals


def _identity_core_strength(face_min: float) -> tuple[float, float]:
    if float(face_min) >= _CORE_LARGE_FACE_MIN:
        return _CORE_LOW_STRENGTH_LARGE, _CORE_PIXEL_MIX_LARGE
    return _CORE_LOW_STRENGTH_MEDIUM, _CORE_PIXEL_MIX_MEDIUM


def _inject_bounded_identity_core(composed, corrected, target, mask, face_min: float, boundary: float):
    import cv2
    import numpy as np

    matched = _colour_match_lab_roi_only(corrected, target, mask)
    binary = (np.asarray(mask) > 80).astype(np.uint8)
    if int(binary.sum()) < 500:
        raise RuntimeError("V265 identity core mask too small")
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5).astype(np.float32)
    start = max(6.0, float(boundary) * _CORE_BOUNDARY_START)
    span = max(14.0, float(boundary) * _CORE_BOUNDARY_SPAN)
    core_alpha = _smoothstep01((distance - start) / max(1.0, span)).astype(np.float32) * binary.astype(np.float32)
    low_strength, pixel_mix = _identity_core_strength(face_min)
    sigma = max(_CORE_SIGMA_MIN, min(_CORE_SIGMA_MAX, float(face_min) * _CORE_SIGMA_FRACTION))
    source_float = matched.astype(np.float32)
    current_float = composed.astype(np.float32)
    source_low = cv2.GaussianBlur(source_float, (0, 0), sigmaX=sigma, sigmaY=sigma)
    current_low = cv2.GaussianBlur(current_float, (0, 0), sigmaX=sigma, sigmaY=sigma)
    low_delta = np.clip(source_low - current_low, -_CORE_DELTA_LIMIT, _CORE_DELTA_LIMIT)
    alpha3 = core_alpha[:, :, None]
    refined = current_float + low_delta * (alpha3 * float(low_strength))
    mix = alpha3 * float(pixel_mix)
    refined = refined * (1.0 - mix) + source_float * mix
    refined = np.clip(refined, 0.0, 255.0).astype(np.uint8)
    refined[binary == 0] = composed[binary == 0]
    return refined, low_strength, pixel_mix, sigma, float(core_alpha.max())


def _structure_first_compose_roi(corrected_roi, target_roi, mask_roi, face_min: float, *, strict: bool):
    import cv2
    import numpy as np

    matched_roi = _colour_match_lab_roi_only(corrected_roi, target_roi, mask_roi)
    ys, xs = np.where(mask_roi > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V265 identity mask ROI empty")
    center = (
        int(round((int(xs.min()) + int(xs.max())) * 0.5)),
        int(round((int(ys.min()) + int(ys.max())) * 0.5)),
    )
    center = (
        max(1, min(int(target_roi.shape[1]) - 2, center[0])),
        max(1, min(int(target_roi.shape[0]) - 2, center[1])),
    )
    integrated_roi = cv2.seamlessClone(matched_roi, target_roi, mask_roi, center, cv2.NORMAL_CLONE)
    binary = (mask_roi > 80).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    boundary = max(v263._BOUNDARY_MIN, min(v263._BOUNDARY_MAX, float(face_min) * v263._BOUNDARY_FRACTION))
    alpha = _smoothstep01(distance / max(1.0, boundary)) * binary.astype(np.float32)
    src = matched_roi.astype(np.float32)
    base = integrated_roi.astype(np.float32)
    fine_low = cv2.GaussianBlur(src, (0, 0), sigmaX=v263._STRUCTURE_SIGMA_FINE, sigmaY=v263._STRUCTURE_SIGMA_FINE)
    coarse_low = cv2.GaussianBlur(src, (0, 0), sigmaX=v263._STRUCTURE_SIGMA_COARSE, sigmaY=v263._STRUCTURE_SIGMA_COARSE)
    structure = fine_low - coarse_low
    detail = src - fine_low
    structure_strength = v263._STRICT_STRUCTURE_STRENGTH if strict else v263._STANDARD_STRUCTURE_STRENGTH
    detail_strength = v263._STRICT_DETAIL_STRENGTH if strict else v263._STANDARD_DETAIL_STRENGTH
    composed = np.clip(
        base
        + structure * (alpha * structure_strength)[:, :, None]
        + detail * (alpha * detail_strength)[:, :, None],
        0.0,
        255.0,
    ).astype(np.uint8)
    blend_mode = "poisson_structure_first_roi"
    if strict:
        composed, low_strength, pixel_mix, sigma, max_alpha = _inject_bounded_identity_core(
            composed, corrected_roi, target_roi, mask_roi, face_min, boundary
        )
        blend_mode += "+bounded_source_identity_core"
        _log(
            "AI_SELFIE_V265_IDENTITY_CORE status=applied low_strength=%.2f pixel_mix=%.2f sigma=%.2f max_alpha=%.3f",
            low_strength, pixel_mix, sigma, max_alpha,
        )
    return composed, blend_mode, boundary, structure_strength, detail_strength


def transfer_attempt(stage1: bytes, source: bytes, yunet_path, dense_path, recognition_path, *, strict: bool):
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    source_bbox, source_pts5 = v253._yunet_face(source_im, yunet_path, label="source_photo3_v265")
    target_bbox, target_pts5 = v253._yunet_face(target[:, :firewall_x], yunet_path, label="target_person_a_v265")
    matrix, sim_rms = v263._similarity_transform(source_pts5, target_pts5)
    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = min(sfw, sfh)
    face_min = min(tfw, tfh)
    if not (0.20 <= scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V265 invalid similarity scale={scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(f"V265 source sampling too small: native_short={native_face_short:.1f}")

    source_dense = v263._dense_landmarks_68(source_im, source_bbox, dense_path, label="source_photo3_v265")
    target_dense = v263._dense_landmarks_68(target, target_bbox, dense_path, label="target_person_a_v265")
    projected_dense = _project_points(matrix, source_dense)
    desired_dense = v263._desired_identity_geometry(projected_dense, target_dense, face_min, strict=strict)
    anatomy_mask = _landmark_anatomy_mask(target.shape, target_bbox, target_pts5, firewall_x)
    mask_pixels = int((anatomy_mask > 80).sum())
    min_mask_pixels = int(round(min(12000.0, max(3200.0, face_min * face_min * 0.30))))
    if mask_pixels < min_mask_pixels:
        raise RuntimeError(f"V265 anatomical identity mask too small: {mask_pixels} < {min_mask_pixels}")
    pad = int(round(max(30.0, min(76.0, face_min * 0.090))))
    x0, y0, x1, y1 = _mask_box(anatomy_mask, pad=pad, firewall_x=firewall_x)
    target_roi = target[y0:y1, x0:x1].copy()
    mask_roi = anatomy_mask[y0:y1, x0:x1].copy()
    warped_roi = _warp_source_direct_to_roi(source_im, matrix, (x0, y0, x1, y1))
    corrected_roi, field_sigma, dense_residuals = _dense_deform_local_roi(
        warped_roi, projected_dense, desired_dense, (x0, y0, x1, y1), face_min
    )
    final_roi, blend_mode, boundary, structure_strength, detail_strength = _structure_first_compose_roi(
        corrected_roi, target_roi, mask_roi, face_min, strict=strict
    )
    final = target.copy()
    final[y0:y1, x0:x1] = final_roi
    final[:, firewall_x:] = target[:, firewall_x:]
    final_bbox, _ = v253._yunet_face(final[:, :firewall_x], yunet_path, label="final_person_a_v265")
    final_dense = v263._dense_landmarks_68(final, final_bbox, dense_path, label="final_person_a_v265")
    source_embedding = v263._mobileface_embedding(source_im, source_dense, recognition_path)
    final_embedding = v263._mobileface_embedding(final, final_dense, recognition_path)
    metrics = dict(v263._quality_metrics(source_embedding, final_embedding, desired_dense, final_dense))
    max_dense_shift = float(np.linalg.norm(dense_residuals, axis=1).max())
    metrics.update({
        "source_face_short": float(native_face_short),
        "target_face_short": float(face_min),
        "similarity_rms_normalized": float(sim_rms / max(face_min, 1.0)),
        "max_dense_shift_normalized": float(max_dense_shift / max(face_min, 1.0)),
    })
    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V265 PNG encode failed")
    output = bytes(encoded.tobytes())
    _log(
        "AI_SELFIE_V265_TRANSFER status=success path=%s landmarks=68 geometry=pipnet_68 roi_only=true "
        "source_face=%.0fx%.0f target_face=%.0fx%.0f scale=%.3f native_face_short=%.1f "
        "max_dense_shift=%.2f field_sigma=%.1f mask_pixels=%s roi=%sx%s blend=%s "
        "structure_strength=%.2f detail_strength=%.2f boundary=%.1f person_b=pixel_locked bytes=%s",
        "strict" if strict else "standard", sfw, sfh, tfw, tfh, scale, native_face_short,
        max_dense_shift, field_sigma, mask_pixels, x1-x0, y1-y0, blend_mode,
        structure_strength, detail_strength, boundary, len(output),
    )
    return output, metrics, desired_dense


def _match_eye_luminance(source_roi, target_roi, mask):
    import cv2
    import numpy as np

    region = np.asarray(mask) > 32
    if int(region.sum()) < 24:
        raise RuntimeError("V265 ocular luminance mask too small")
    src_lab = cv2.cvtColor(source_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt_lab = cv2.cvtColor(target_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    s = src_lab[:, :, 0][region]
    t = tgt_lab[:, :, 0][region]
    sm, tm = float(s.mean()), float(t.mean())
    ss, ts = float(s.std()), float(t.std())
    gain = 1.0 if ss < 1.0 else max(0.82, min(1.18, ts / ss))
    src_lab[:, :, 0] = np.clip((src_lab[:, :, 0] - sm) * gain + tm, 0.0, 255.0)
    return cv2.cvtColor(src_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def _eye_box(points, frame_w: int, frame_h: int):
    import numpy as np

    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    eye_w = max(8.0, float(pts[:, 0].max() - pts[:, 0].min()))
    eye_h = max(5.0, float(pts[:, 1].max() - pts[:, 1].min()))
    margin = int(round(max(_OCULAR_MIN_MARGIN, min(_OCULAR_MAX_MARGIN, eye_w * _OCULAR_MARGIN_FRACTION))))
    x0 = max(0, int(round(float(pts[:, 0].min()))) - margin)
    y0 = max(0, int(round(float(pts[:, 1].min()))) - margin)
    x1 = min(int(frame_w), int(round(float(pts[:, 0].max()))) + margin + 1)
    y1 = min(int(frame_h), int(round(float(pts[:, 1].max()))) + margin + 1)
    if x1 <= x0 + 6 or y1 <= y0 + 4:
        raise RuntimeError("V265 ocular eye box too small")
    return x0, y0, x1, y1, max(eye_w, eye_h)


def _ocular_mask(points, box, eye_span: float):
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    local = np.asarray(points, dtype=np.float32).reshape(-1, 2).copy()
    local[:, 0] -= float(x0)
    local[:, 1] -= float(y0)
    mask = np.zeros((y1-y0, x1-x0), dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(local).astype(np.int32), 255, lineType=cv2.LINE_AA)
    dilate = max(1, int(round(float(eye_span) * 0.07)))
    kernel_size = max(3, dilate * 2 + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    mask = cv2.dilate(mask, kernel, iterations=1)
    sigma = max(_OCULAR_MIN_FEATHER, min(_OCULAR_MAX_FEATHER, float(eye_span) * _OCULAR_FEATHER_FRACTION))
    return cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, sigmaY=sigma), float(sigma)


def apply_ocular_lock(stage1: bytes, output: bytes, source: bytes, desired_dense, yunet_path, dense_path, recognition_path, base_metrics):
    """Restore source eye texture through the same V265 geometry. Fail closed on error."""
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    final = v253._decode_bgr(output)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    if final.shape[:2] != (th, tw):
        raise RuntimeError("V265 ocular output/target dimension mismatch")
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    source_bbox, source_pts5 = v253._yunet_face(source_im, yunet_path, label="source_photo3_v265_ocular")
    _, target_pts5 = v253._yunet_face(target[:, :firewall_x], yunet_path, label="target_person_a_v265_ocular")
    matrix, _ = v263._similarity_transform(source_pts5, target_pts5)
    source_dense = v263._dense_landmarks_68(source_im, source_bbox, dense_path, label="source_photo3_v265_ocular")
    projected_dense = _project_points(matrix, source_dense)
    face_min = float(base_metrics.get("target_face_short", 0.0) or 0.0)
    if face_min <= 0.0:
        raise RuntimeError("V265 ocular missing target face size")

    sigmas: list[float] = []
    for eye_ids in (v263._RIGHT_EYE, v263._LEFT_EYE):
        eye_points = np.asarray(desired_dense, dtype=np.float32)[list(eye_ids)]
        x0, y0, x1, y1, eye_span = _eye_box(eye_points, final.shape[1], final.shape[0])
        box = (x0, y0, x1, y1)
        warped = _warp_source_direct_to_roi(source_im, matrix, box)
        corrected, _, _ = _dense_deform_local_roi(warped, projected_dense, desired_dense, box, face_min)
        mask, sigma = _ocular_mask(eye_points, box, eye_span)
        target_roi = final[y0:y1, x0:x1]
        matched = _match_eye_luminance(corrected, target_roi, mask)
        alpha = (mask.astype(np.float32) / 255.0)[:, :, None] * float(_OCULAR_ALPHA)
        final[y0:y1, x0:x1] = np.clip(
            matched.astype(np.float32) * alpha + target_roi.astype(np.float32) * (1.0 - alpha),
            0.0,
            255.0,
        ).astype(np.uint8)
        sigmas.append(sigma)
    final[:, firewall_x:] = target[:, firewall_x:]

    final_bbox, _ = v253._yunet_face(final[:, :firewall_x], yunet_path, label="final_person_a_v265_ocular")
    final_dense = v263._dense_landmarks_68(final, final_bbox, dense_path, label="final_person_a_v265_ocular")
    source_embedding = v263._mobileface_embedding(source_im, source_dense, recognition_path)
    final_embedding = v263._mobileface_embedding(final, final_dense, recognition_path)
    metrics_after = dict(v263._quality_metrics(source_embedding, final_embedding, desired_dense, final_dense))
    for key in ("source_face_short", "target_face_short", "similarity_rms_normalized", "max_dense_shift_normalized"):
        if key in base_metrics:
            metrics_after[key] = float(base_metrics[key])
    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V265 ocular PNG encode failed")
    result = bytes(encoded.tobytes())
    _log(
        "AI_SELFIE_V265_OCULAR_LOCK status=applied eyes=2 shared_dense68=true alpha=%.2f feather_sigma=%s "
        "identity_before=%.4f identity_after=%.4f eye_asym_before=%.4f eye_asym_after=%.4f bytes=%s",
        _OCULAR_ALPHA,
        ",".join(f"{v:.2f}" for v in sigmas),
        float(base_metrics.get("identity_similarity_cosine", 0.0)),
        float(metrics_after.get("identity_similarity_cosine", 0.0)),
        float(base_metrics.get("eye_asymmetry_delta", 0.0)),
        float(metrics_after.get("eye_asymmetry_delta", 0.0)),
        len(result),
    )
    return result, metrics_after


__all__ = [
    "VERSION",
    "transfer_attempt",
    "apply_ocular_lock",
    "visual_refinement_reasons",
    "visual_quality_score",
    "strict_geometry_safe",
    "prefer_strict_refinement",
    "_project_points",
    "_landmark_anatomy_mask",
    "_mask_box",
]
