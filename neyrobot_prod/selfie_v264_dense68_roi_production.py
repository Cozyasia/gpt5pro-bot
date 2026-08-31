# -*- coding: utf-8 -*-
"""V264: production-safe 68-landmark identity transfer with ROI-only heavy work.

V263 established the desired identity architecture (PIPNet 68 landmarks + MobileFace
quality gate) but its production-size implementation still allocated full-frame LAB,
warp and compositing buffers. At 1856x2304 that could exceed the 512 MB Render
instance limit and restart the process after dense landmark detection.

V264 keeps the identity contract and removes that memory failure mode:
- YuNet five points are used only for face selection and one global similarity pose;
- PIPNet 68 points own the local identity geometry and one smooth deformation field;
- all float32 geometry, LAB colour matching, Poisson integration and detail work is
  restricted to PERSON-A's compact ROI;
- there is no full-frame source warp and no full-frame float32 LAB conversion;
- PERSON-B remains pixel-locked, the no-neck anatomical boundary is retained, and
  final Telegram delivery remains the original lossless PNG document path;
- MobileFace + dense landmark metrics gate the result; one strict retry is allowed;
- a hard-passing standard result with borderline high-resolution eye geometry may
  use that same single strict attempt as a visual refinement, then keep whichever
  hard-passing candidate has the stronger identity/geometry score;
- only model/inference infrastructure failure may fall back to concrete V262.

No Telegram callback, payment, scene-selection or delivery route is added here.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v262_landmark_field_compositor as v262
from neyrobot_prod import selfie_v263_dense_identity_lock as v263

VERSION = "v264-dense68-roi-production-2026-08-31"
_INSTALLED = False
_BASE_V262_ENFORCE = None

_REFINEMENT_LARGE_FACE_MIN = 500.0
_REFINEMENT_MEDIUM_FACE_MIN = 360.0
_REFINEMENT_LARGE_EYE_ERROR = 0.032
_REFINEMENT_LARGE_INTEROCULAR = 0.030
_REFINEMENT_LARGE_EYE_ASYMMETRY = 0.008
_REFINEMENT_LARGE_INNER_NME = 0.040
_REFINEMENT_MEDIUM_EYE_ERROR = 0.045
_REFINEMENT_MEDIUM_INTEROCULAR = 0.040
_REFINEMENT_MEDIUM_EYE_ASYMMETRY = 0.020
_REFINEMENT_MEDIUM_INNER_NME = 0.055


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _visual_refinement_reasons(metrics: dict[str, float]) -> list[str]:
    """Detect borderline geometry that a permissive hard gate intentionally accepts."""
    face_short = float(metrics.get("target_face_short", 0.0) or 0.0)
    if face_short < _REFINEMENT_MEDIUM_FACE_MIN:
        return []

    if face_short >= _REFINEMENT_LARGE_FACE_MIN:
        eye_limit = _REFINEMENT_LARGE_EYE_ERROR
        interocular_limit = _REFINEMENT_LARGE_INTEROCULAR
        asym_limit = _REFINEMENT_LARGE_EYE_ASYMMETRY
        inner_limit = _REFINEMENT_LARGE_INNER_NME
    else:
        eye_limit = _REFINEMENT_MEDIUM_EYE_ERROR
        interocular_limit = _REFINEMENT_MEDIUM_INTEROCULAR
        asym_limit = _REFINEMENT_MEDIUM_EYE_ASYMMETRY
        inner_limit = _REFINEMENT_MEDIUM_INNER_NME

    reasons: list[str] = []
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


def _visual_quality_score(metrics: dict[str, float]) -> float:
    """Rank two already hard-passing candidates; higher is better."""
    identity = float(metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    worst_eye = max(
        float(metrics.get("left_eye_error", 1.0) or 1.0),
        float(metrics.get("right_eye_error", 1.0) or 1.0),
    )
    interocular = float(metrics.get("interocular_ratio_delta", 1.0) or 1.0)
    inner_nme = float(metrics.get("inner_face_landmark_nme", 1.0) or 1.0)
    eye_asymmetry = float(metrics.get("eye_asymmetry_delta", 1.0) or 1.0)
    nose_mouth = float(metrics.get("nose_mouth_axis_delta", 1.0) or 1.0)
    return (
        identity
        - 2.8 * worst_eye
        - 1.8 * interocular
        - 1.0 * inner_nme
        - 1.2 * eye_asymmetry
        - 0.5 * nose_mouth
    )


def _prefer_strict_refinement(standard_metrics: dict[str, float], strict_metrics: dict[str, float]) -> bool:
    """Prefer strict only when it improves visual geometry without sacrificing identity."""
    standard_score = _visual_quality_score(standard_metrics)
    strict_score = _visual_quality_score(strict_metrics)
    if strict_score >= standard_score + 0.004:
        return True

    standard_eye = max(
        float(standard_metrics.get("left_eye_error", 1.0) or 1.0),
        float(standard_metrics.get("right_eye_error", 1.0) or 1.0),
    )
    strict_eye = max(
        float(strict_metrics.get("left_eye_error", 1.0) or 1.0),
        float(strict_metrics.get("right_eye_error", 1.0) or 1.0),
    )
    standard_identity = float(standard_metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    strict_identity = float(strict_metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    return strict_eye <= standard_eye - 0.003 and strict_identity >= standard_identity - 0.080


def _colour_match_lab_roi_only(source_roi, target_roi, mask_roi):
    """Match LAB statistics entirely inside the compact PERSON-A ROI."""
    import cv2
    import numpy as np

    region = mask_roi > 80
    if int(region.sum()) < 500:
        return source_roi.copy()

    src_lab = cv2.cvtColor(source_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt_lab = cv2.cvtColor(target_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    out_lab = src_lab.copy()
    for channel in range(3):
        src_values = src_lab[:, :, channel][region]
        tgt_values = tgt_lab[:, :, channel][region]
        src_mean, tgt_mean = float(src_values.mean()), float(tgt_values.mean())
        src_std, tgt_std = float(src_values.std()), float(tgt_values.std())
        gain = 1.0 if src_std < 1.0 else max(0.78, min(1.22, tgt_std / src_std))
        adjusted = (src_lab[:, :, channel] - src_mean) * gain + tgt_mean
        out_lab[:, :, channel] = np.clip(adjusted, 0.0, 255.0)

    return cv2.cvtColor(out_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def _warp_source_direct_to_roi(source_im, matrix, box):
    """Apply the global source pose directly into ROI coordinates, never full frame."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    roi_w, roi_h = int(x1 - x0), int(y1 - y0)
    local_matrix = np.asarray(matrix, dtype=np.float32).copy()
    local_matrix[0, 2] -= float(x0)
    local_matrix[1, 2] -= float(y0)
    return cv2.warpAffine(
        source_im,
        local_matrix,
        (roi_w, roi_h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _dense_deform_local_roi(warped_roi, projected_dense, desired_dense, box, face_min: float):
    """One 68-point inverse field in local ROI coordinates with bounded memory."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    roi_w, roi_h = int(x1 - x0), int(y1 - y0)
    if warped_roi.shape[1] != roi_w or warped_roi.shape[0] != roi_h:
        raise RuntimeError(
            f"V264 warped ROI shape mismatch: got={warped_roi.shape[1]}x{warped_roi.shape[0]} expected={roi_w}x{roi_h}"
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
    disp_x = sum_dx * inv * support
    disp_y = sum_dy * inv * support
    map_x = np.broadcast_to(gx, (roi_h, roi_w)).copy() - disp_x
    map_y = np.broadcast_to(gy, (roi_h, roi_w)).copy() - disp_y
    corrected_roi = cv2.remap(
        warped_roi,
        map_x,
        map_y,
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return corrected_roi, sigma, residuals


def _structure_first_compose_roi(corrected_roi, target_roi, mask_roi, face_min: float, *, strict: bool):
    """ROI-only colour/integration/detail composition; no full-frame float buffers."""
    import cv2
    import numpy as np

    matched_roi = _colour_match_lab_roi_only(corrected_roi, target_roi, mask_roi)
    ys, xs = np.where(mask_roi > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V264 identity mask ROI empty")
    center = (
        int(round((int(xs.min()) + int(xs.max())) * 0.5)),
        int(round((int(ys.min()) + int(ys.max())) * 0.5)),
    )
    center = (
        max(1, min(int(target_roi.shape[1]) - 2, center[0])),
        max(1, min(int(target_roi.shape[0]) - 2, center[1])),
    )

    try:
        integrated_roi = cv2.seamlessClone(matched_roi, target_roi, mask_roi, center, cv2.NORMAL_CLONE)
        blend_mode = "poisson_structure_first_roi"
    except Exception as exc:
        _log("AI_SELFIE_V264_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        integrated_roi = target_roi.copy()
        blend_mode = "target_plus_controlled_structure_roi"

    binary = (mask_roi > 80).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    boundary = max(v263._BOUNDARY_MIN, min(v263._BOUNDARY_MAX, float(face_min) * v263._BOUNDARY_FRACTION))
    alpha = v262._smoothstep01(distance / max(1.0, boundary)) * binary.astype(np.float32)

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
    return composed, blend_mode, boundary, structure_strength, detail_strength


def _transfer_attempt_roi(stage1: bytes, source: bytes, yunet_path, dense_path, recognition_path, *, strict: bool):
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))

    source_bbox, source_pts5 = v253._yunet_face(source_im, yunet_path, label="source_photo3_v264")
    target_bbox, target_pts5 = v253._yunet_face(target[:, :firewall_x], yunet_path, label="target_person_a_v264")
    matrix, sim_rms = v263._similarity_transform(source_pts5, target_pts5)

    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = min(sfw, sfh)
    face_min = min(tfw, tfh)
    if not (0.20 <= scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V264 invalid similarity scale={scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(f"V264 source sampling too small: native_short={native_face_short:.1f}")

    source_dense = v263._dense_landmarks_68(source_im, source_bbox, dense_path, label="source_photo3")
    target_dense = v263._dense_landmarks_68(target, target_bbox, dense_path, label="target_person_a")
    projected_dense = v262._project_points(matrix, source_dense)
    desired_dense = v263._desired_identity_geometry(projected_dense, target_dense, face_min, strict=strict)

    anatomy_mask = v262._landmark_anatomy_mask(target.shape, target_bbox, target_pts5, firewall_x)
    mask_pixels = int((anatomy_mask > 80).sum())
    min_mask_pixels = int(round(min(12000.0, max(3200.0, face_min * face_min * 0.30))))
    if mask_pixels < min_mask_pixels:
        raise RuntimeError(f"V264 anatomical identity mask too small: {mask_pixels} < {min_mask_pixels}")

    pad = int(round(max(30.0, min(76.0, face_min * 0.090))))
    box = v262._mask_box(anatomy_mask, pad=pad, firewall_x=firewall_x)
    x0, y0, x1, y1 = box
    target_roi = target[y0:y1, x0:x1].copy()
    mask_roi = anatomy_mask[y0:y1, x0:x1].copy()

    warped_roi = _warp_source_direct_to_roi(source_im, matrix, box)
    corrected_roi, field_sigma, dense_residuals = _dense_deform_local_roi(
        warped_roi, projected_dense, desired_dense, box, face_min
    )
    final_roi, blend_mode, boundary, structure_strength, detail_strength = _structure_first_compose_roi(
        corrected_roi, target_roi, mask_roi, face_min, strict=strict
    )

    final = target.copy()
    final[y0:y1, x0:x1] = final_roi
    final[:, firewall_x:] = target[:, firewall_x:]

    final_bbox, _ = v253._yunet_face(final[:, :firewall_x], yunet_path, label="final_person_a_v264")
    final_dense = v263._dense_landmarks_68(final, final_bbox, dense_path, label="final_person_a")
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
        raise RuntimeError("V264 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())
    path = "strict" if strict else "standard"
    _log(
        "AI_SELFIE_V264_TRANSFER status=success path=%s method=dense68_identity_field_roi_only "
        "geometry_mode=pipnet_68 landmarks=68 source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "global_transform=similarity similarity_rms=%.2f scale=%.3f native_face_short=%.1f "
        "max_dense_shift=%.2f field_sigma=%.1f mask=landmark_anatomical_hull mask_pixels=%s mask_min_pixels=%s "
        "roi=%sx%s roi_only=true full_frame_source_warp=false full_frame_float=false colour_match=lab_roi_only "
        "blend=%s structure_first=true structure_strength=%.2f detail_strength=%.2f boundary=%.1f "
        "independent_eye_patch=false raw_low_frequency_reinject=false solid_source_core=false no_neck=true "
        "person_b_untouched=true final_owner=v264 delivery=v253_original_document output=png bytes=%s "
        "source_pixels=true synthetic_face=false",
        path, sfw, sfh, tfw, tfh, sim_rms, scale, native_face_short, max_dense_shift, field_sigma,
        mask_pixels, min_mask_pixels, x1 - x0, y1 - y0, blend_mode,
        structure_strength, detail_strength, boundary, len(output),
    )
    return output, metrics, desired_dense


async def _true_face_transfer_v264(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    if int(source_photo_no) != 3:
        raise RuntimeError(f"V264 requires authoritative photo #3, got #{source_photo_no}")

    try:
        yunet_path = await v253._ensure_yunet_model()
        dense_path, recognition_path = await v263._ensure_identity_models()

        standard, metrics, _ = _transfer_attempt_roi(
            bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=False
        )
        passed, failures = v263._quality_gate(metrics)
        refinement_reasons = _visual_refinement_reasons(metrics) if passed else []
        if passed and not refinement_reasons:
            v263._log_quality(
                metrics, path="v264_standard", passed=True,
                strict_retry_triggered=False, strict_retry_success=False, failures=[]
            )
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_standard"
            runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_standard"
            runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(metrics)
            return standard, "opencv_dense68_roi_identity_lock_standard"

        if passed:
            v263._log_quality(
                metrics, path="v264_standard", passed=True,
                strict_retry_triggered=True, strict_retry_success=False, failures=[]
            )
            retry_reason = "visual_refinement:" + "|".join(refinement_reasons)
            _log(
                "AI_SELFIE_V264_REFINEMENT_RETRY status=triggered strict_retry_triggered=true reason=%s "
                "target_face_short=%.1f standard_score=%.5f",
                "|".join(refinement_reasons), float(metrics.get("target_face_short", 0.0)),
                _visual_quality_score(metrics),
            )
        else:
            v263._log_quality(
                metrics, path="v264_standard", passed=False,
                strict_retry_triggered=True, strict_retry_success=False, failures=failures
            )
            retry_reason = "identity_quality_gate"

        _log("AI_SELFIE_V264_STRICT_RETRY strict_retry_triggered=true reason=%s", retry_reason)
        strict, strict_metrics, _ = _transfer_attempt_roi(
            bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=True
        )
        strict_passed, strict_failures = v263._quality_gate(strict_metrics)
        v263._log_quality(
            strict_metrics, path="v264_strict", passed=strict_passed,
            strict_retry_triggered=True, strict_retry_success=strict_passed, failures=strict_failures
        )

        if passed:
            prefer_strict = bool(strict_passed and _prefer_strict_refinement(metrics, strict_metrics))
            selected_metrics = strict_metrics if prefer_strict else metrics
            standard_score = _visual_quality_score(metrics)
            strict_score = _visual_quality_score(strict_metrics) if strict_passed else float("-inf")
            selected = "strict" if prefer_strict else "standard"
            _log(
                "AI_SELFIE_V264_REFINEMENT_SELECT status=success selected=%s strict_passed=%s "
                "standard_score=%.5f strict_score=%.5f standard_worst_eye=%.4f strict_worst_eye=%.4f",
                selected, str(bool(strict_passed)).lower(), standard_score, strict_score,
                max(float(metrics.get("left_eye_error", 1.0)), float(metrics.get("right_eye_error", 1.0))),
                max(float(strict_metrics.get("left_eye_error", 1.0)), float(strict_metrics.get("right_eye_error", 1.0))),
            )
            runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(selected_metrics)
            if prefer_strict:
                runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_refined_strict"
                runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_refined_strict"
                return strict, "opencv_dense68_roi_identity_lock_refined_strict"
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_standard_retained"
            runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_standard_retained"
            return standard, "opencv_dense68_roi_identity_lock_standard_retained"

        runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_strict"
        runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(strict_metrics)
        if strict_passed:
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_strict"
            return strict, "opencv_dense68_roi_identity_lock_strict"

        _log(
            "AI_SELFIE_V264_IDENTITY_REJECT status=rejected strict_retry_triggered=true strict_retry_success=false "
            "reason=%s person_b_untouched=true delivery=blocked",
            "|".join(strict_failures) if strict_failures else "quality_gate_unknown",
        )
        raise RuntimeError("V264 identity quality gate rejected final PERSON-A after strict retry")

    except Exception as exc:
        # Only V263 model/cache/inference infrastructure failures are allowed to
        # downgrade to the concrete V262 availability path. Identity rejection and
        # ordinary input/geometry failures remain visible failures, never silent V262.
        try:
            from neyrobot_prod.selfie_v263_runtime_safety import V263InfrastructureUnavailable
        except Exception:
            V263InfrastructureUnavailable = ()  # type: ignore[assignment,misc]
        if V263InfrastructureUnavailable and isinstance(exc, V263InfrastructureUnavailable):
            _log(
                "AI_SELFIE_V264_INFRA_FALLBACK status=fallback_v262 reason=%s:%s "
                "identity_gate_bypass=false rollback=v262",
                type(exc).__name__, str(exc)[:300],
            )
            runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v262_degraded_infrastructure"
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_v262_infrastructure_fallback"
            return await v262._true_face_transfer_v262(runtime, stage1, source, source_photo_no)
        raise


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert the V262 safety base and make V264 the sole final transfer owner."""
    global _BASE_V262_ENFORCE
    if not callable(_BASE_V262_ENFORCE):
        raise RuntimeError("V264 base V262 enforcer was not captured")

    _BASE_V262_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = v262._modules()
    transfer._true_face_transfer = _true_face_transfer_v264
    delivery._deliver = v253._deliver_original

    from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
    from neyrobot_prod import selfie_v255_source_face_gate as v255
    from neyrobot_prod import selfie_v257_native_sampling_guard as v257
    from neyrobot_prod import selfie_v258_inner_face_integration as v258
    from neyrobot_prod import selfie_v259_eye_landmark_protection as v259
    from neyrobot_prod import selfie_v260_eye_roi_memory_safe as v260
    from neyrobot_prod import selfie_v261_edge_harmonization as v261

    for mod in (
        v263, v262, v261, v260, v259, v258, v257, v256, v255, v254,
        v253, v252, v251, v247, v246,
    ):
        mod.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (
        transfer, google, ui, delivery, v241, v245, v246, v247, v249, v250,
        v251, v252, v253, v254, v255, v256, v257, v258, v259, v260, v261,
        v262, v263,
    ):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v264-v262-safety-dense68-roi-identity-lock-quality-gate-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini scene/PERSON-B -> V262 safety base -> YuNet global similarity only -> "
            "PIPNet 68-point source-dominant ROI geometry -> ROI-only LAB/Poisson/detail -> "
            "MobileFace+dense identity gate -> one strict retry/refinement -> V253 original document"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V264_ENFORCE status=ok base=v262 final_owner=v264 landmarks=68 "
        "geometry=source_dominant_dense_identity_field roi_only=true full_frame_source_warp=false "
        "full_frame_float=false colour_match=lab_roi_only quality_gate=mobileface_plus_dense "
        "strict_retry=automatic visual_refinement=size_aware independent_eye_patch=false "
        "mask=landmark_anatomical_hull source_gate=anatomical_inner_face no_neck=true person_b=pixel_locked "
        "delivery=v253_original_document callback_payment_scene_unchanged=true version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V262_ENFORCE
    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return
    current = v262.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V262_ENFORCE = current
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V264 dense68 ROI-only production identity runtime installed", flush=True)


__all__ = [
    "VERSION", "install", "enforce_runtime", "_true_face_transfer_v264",
    "_transfer_attempt_roi", "_dense_deform_local_roi", "_colour_match_lab_roi_only",
    "_warp_source_direct_to_roi", "_structure_first_compose_roi",
    "_visual_refinement_reasons", "_visual_quality_score", "_prefer_strict_refinement",
]
