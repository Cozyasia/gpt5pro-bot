# -*- coding: utf-8 -*-
"""V260: memory-safe eye correction over the proven V258 compositor.

V259 production telemetry showed two hard Render instance restarts immediately after
YuNet target landmarks.  The V259 eye stage translated two full 1856x2304 frames per
eye and repeatedly materialised float32 full-frame composites.  On a 512 MB service
that can create a short RSS spike which is invisible to 30-second metrics and kills
the process before Python can emit a traceback.

V260 keeps the visual intent but removes the full-frame eye work:
- V258 remains the complete, proven face compositor and produces the base PNG;
- YuNet landmarks are re-read only to calculate the two bounded eye residuals;
- each source eye is warped directly into a small target ROI (normally <200x140);
- LAB matching and raw-source ocular restoration are done only inside that ROI;
- no full-frame per-eye warp, no full-frame per-eye float32 blend and no extra
  Poisson pass are performed;
- PERSON-B remains untouched because eye ROIs are clipped left of the firewall;
- any V260-specific failure falls back to the proven V258 transfer;
- no Telegram callback, payment, UX, scene-owner or provider handler is added.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v258_inner_face_integration as v258
from neyrobot_prod import selfie_v259_eye_landmark_protection as v259

VERSION = "v260-eye-roi-memory-safe-2026-08-26"
_INSTALLED = False
_BASE_V259_ENFORCE = None

_EYE_SUPPORT_WEIGHT = 0.92
_EYE_RAW_CORE_WEIGHT = 0.97
_EYE_RAW_MIX = 0.90
_EYE_MAX_LOCAL_SHIFT = 36.0


def _modules():
    return v256._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _project_points(matrix, points):
    import numpy as np

    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    ones = np.ones((pts.shape[0], 1), dtype=np.float32)
    hom = np.concatenate([pts, ones], axis=1)
    return hom @ np.asarray(matrix, dtype=np.float32).T


def _ellipse_mask(height: int, width: int, center, axes, sigma: float):
    import cv2
    import numpy as np

    mask = np.zeros((int(height), int(width)), dtype=np.uint8)
    cx = max(0, min(int(width) - 1, int(round(float(center[0])))))
    cy = max(0, min(int(height) - 1, int(round(float(center[1])))))
    ax = max(3, int(round(float(axes[0]))))
    ay = max(2, int(round(float(axes[1]))))
    cv2.ellipse(mask, (cx, cy), (ax, ay), 0.0, 0.0, 360.0, 255, -1, lineType=cv2.LINE_AA)
    if float(sigma) > 0.0:
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=float(sigma), sigmaY=float(sigma))
    return mask


def _eye_roi(center, support_axes, support_sigma: float, *, width: int, height: int, firewall_x: int):
    """Return a compact target-space box around one eye."""
    pad_x = int(math.ceil(float(support_axes[0]) + 4.0 * float(support_sigma) + 6.0))
    pad_y = int(math.ceil(float(support_axes[1]) + 4.0 * float(support_sigma) + 6.0))
    cx, cy = float(center[0]), float(center[1])
    x0 = max(0, int(math.floor(cx - pad_x)))
    y0 = max(0, int(math.floor(cy - pad_y)))
    x1 = min(int(width), int(firewall_x), int(math.ceil(cx + pad_x + 1)))
    y1 = min(int(height), int(math.ceil(cy + pad_y + 1)))
    if x1 - x0 < 20 or y1 - y0 < 14:
        raise RuntimeError(f"V260 eye ROI too small: {x1-x0}x{y1-y0}")
    return x0, y0, x1, y1


def _warp_source_roi(source_im, matrix, residual, box):
    """Warp source directly into a compact target ROI; never allocate a target-size frame."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    roi_w, roi_h = int(x1 - x0), int(y1 - y0)
    local = np.asarray(matrix, dtype=np.float32).copy()
    local[0, 2] += float(residual[0]) - float(x0)
    local[1, 2] += float(residual[1]) - float(y0)
    return cv2.warpAffine(
        source_im,
        local,
        (roi_w, roi_h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _source_pixel_transfer_v260(stage1: bytes, source: bytes, model_path) -> bytes:
    """Run proven V258 first, then correct only two compact eye ROIs."""
    import cv2
    import numpy as np

    # V258 is the stability boundary.  It already owns the face mask, no-neck gate,
    # target-heavy outer ring, adaptive detail core and PERSON-B firewall.
    base_png = v258._source_pixel_transfer_v258(bytes(stage1 or b""), bytes(source or b""), model_path)
    _log("AI_SELFIE_V260_BASE status=success base=v258 bytes=%s", len(base_png))

    final = v253._decode_bgr(base_png)
    source_im = v253._decode_bgr(source)
    target = v253._decode_bgr(stage1)
    th, tw = target.shape[:2]
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))

    source_bbox, source_pts = v253._yunet_face(source_im, model_path, label="source_photo3_v260")
    target_bbox, target_pts = v253._yunet_face(
        target[:, :firewall_x], model_path, label="target_person_a_v260"
    )
    matrix, transform_mode, sim_err, fit_err, anisotropy = v254._choose_transform(source_pts, target_pts)

    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    mean_scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = float(min(sfw, sfh))
    if not (0.20 <= mean_scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V260 invalid face transform scale={mean_scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(f"V260 source sampling too small: native_short={native_face_short:.1f}")

    projected_pts = _project_points(matrix, source_pts)
    face_min = float(min(tfw, tfh))
    support_axes = (
        max(18.0, min(88.0, tfw * 0.085)),
        max(10.0, min(58.0, tfh * 0.045)),
    )
    raw_axes = (
        max(12.0, min(62.0, tfw * 0.060)),
        max(7.0, min(40.0, tfh * 0.030)),
    )
    support_sigma = max(3.0, min(9.0, face_min * 0.009))
    raw_sigma = max(2.0, min(5.0, face_min * 0.0045))

    # We no longer need the full stage-1 target after landmarks.  Drop it before
    # any eye warp so the transient working set stays small.
    del target

    eye_residuals = []
    eye_shifts = []
    roi_sizes = []

    for eye_index in (0, 1):
        residual = np.asarray(target_pts[eye_index], dtype=np.float32) - np.asarray(
            projected_pts[eye_index], dtype=np.float32
        )
        residual_norm = float(np.linalg.norm(residual))
        if residual_norm > _EYE_MAX_LOCAL_SHIFT:
            raise RuntimeError(
                f"V260 eye residual too large: eye={eye_index} residual={residual_norm:.2f}px"
            )

        box = _eye_roi(
            target_pts[eye_index], support_axes, support_sigma,
            width=tw, height=th, firewall_x=firewall_x,
        )
        x0, y0, x1, y1 = box
        roi_w, roi_h = x1 - x0, y1 - y0
        raw_patch = _warp_source_roi(source_im, matrix, residual, box)
        final_roi = final[y0:y1, x0:x1]

        local_center = (
            float(target_pts[eye_index][0]) - float(x0),
            float(target_pts[eye_index][1]) - float(y0),
        )
        support_mask = _ellipse_mask(roi_h, roi_w, local_center, support_axes, support_sigma)
        matched_patch = v253._colour_match_lab(raw_patch, final_roi, support_mask)

        support_alpha = (
            support_mask.astype(np.float32) / 255.0 * _EYE_SUPPORT_WEIGHT
        )[:, :, None]
        composed = np.clip(
            matched_patch.astype(np.float32) * support_alpha
            + final_roi.astype(np.float32) * (1.0 - support_alpha),
            0,
            255,
        ).astype(np.uint8)

        raw_mask = _ellipse_mask(roi_h, roi_w, local_center, raw_axes, raw_sigma)
        raw_alpha = (
            raw_mask.astype(np.float32) / 255.0 * _EYE_RAW_CORE_WEIGHT
        )[:, :, None]
        ocular_source = np.clip(
            raw_patch.astype(np.float32) * _EYE_RAW_MIX
            + matched_patch.astype(np.float32) * (1.0 - _EYE_RAW_MIX),
            0,
            255,
        ).astype(np.uint8)
        final_roi[:] = np.clip(
            ocular_source.astype(np.float32) * raw_alpha
            + composed.astype(np.float32) * (1.0 - raw_alpha),
            0,
            255,
        ).astype(np.uint8)

        eye_residuals.append(residual_norm)
        eye_shifts.append((float(residual[0]), float(residual[1])))
        roi_sizes.append((roi_w, roi_h))
        _log(
            "AI_SELFIE_V260_EYE status=success eye=%s residual=%.2f shift=%.2f,%.2f roi=%sx%s "
            "full_frame_eye_warp=false",
            eye_index, residual_norm, float(residual[0]), float(residual[1]), roi_w, roi_h,
        )

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V260 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    _log(
        "AI_SELFIE_V260_TRANSFER status=success method=v258_base_plus_roi_eye_landmark_source_pixels "
        "base=v258 transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f "
        "native_face_short=%.1f eye0_residual=%.2f eye1_residual=%.2f "
        "eye0_shift=%.2f,%.2f eye1_shift=%.2f,%.2f eye0_roi=%sx%s eye1_roi=%sx%s "
        "eye_support=%.2f eye_raw_core=%.2f eye_raw_mix=%.2f full_frame_eye_warp=false "
        "full_frame_eye_float_blend=false person_b_untouched=true provider_bypassed=true "
        "delivery=v253_original_document output=png bytes=%s source_pixels=true synthetic_face=false",
        transform_mode, sim_err, fit_err, anisotropy, mean_scale, native_face_short,
        eye_residuals[0], eye_residuals[1],
        eye_shifts[0][0], eye_shifts[0][1], eye_shifts[1][0], eye_shifts[1][1],
        roi_sizes[0][0], roi_sizes[0][1], roi_sizes[1][0], roi_sizes[1][1],
        _EYE_SUPPORT_WEIGHT, _EYE_RAW_CORE_WEIGHT, _EYE_RAW_MIX, len(output),
    )
    return output


async def _true_face_transfer_v260(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V260 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v260(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_eye_roi_source_pixels_v260"
        return final, "opencv_yunet_eye_roi_memory_safe_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V260_TRANSFER status=fallback_v258 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        return await v258._true_face_transfer_v258(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V259 bindings, then replace only its crashing full-frame eye transfer."""
    global _BASE_V259_ENFORCE
    if not callable(_BASE_V259_ENFORCE):
        raise RuntimeError("V260 base V259 enforcer was not captured")

    _BASE_V259_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v260
    delivery._deliver = v253._deliver_original

    # Every historical late enforcer returns to V260 so V259 cannot regain the
    # full-frame eye path after startup or command re-enforcement.
    v259.enforce_runtime = enforce_runtime
    v258.enforce_runtime = enforce_runtime
    from neyrobot_prod import selfie_v257_native_sampling_guard as v257
    from neyrobot_prod import selfie_v255_source_face_gate as v255
    v257.enforce_runtime = enforce_runtime
    v256.enforce_runtime = enforce_runtime
    v255.enforce_runtime = enforce_runtime
    v254.enforce_runtime = enforce_runtime
    v253.enforce_runtime = enforce_runtime
    v252.enforce_runtime = enforce_runtime
    v251.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (
        transfer, google, ui, delivery,
        v241, v245, v246, v247, v249, v250, v251, v252,
        v253, v254, v255, v256, v257, v258, v259,
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
        runtime.CELEBRITY_SELFIE_ROUTE = (
            "v260-front-camera-yunet-v258-base-eye-roi-memory-safe-source-pixels-lossless-document"
        )
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> V258 proven real source-pixel compositor -> "
            "V260 bounded YuNet per-eye correction in compact ROIs only -> native PNG -> "
            "V253 original Telegram document; V258 fallback retained"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V260_ENFORCE status=ok base=v258_via_v259_bindings eye_landmark_local_correction=true "
        "eye_processing=roi_only full_frame_eye_warp=false full_frame_eye_float_blend=false "
        "eye_support=%.2f eye_raw_core=%.2f eye_raw_mix=%.2f eye_shift_limit=%.1f "
        "source_gate=v255 no_neck=true delivery=v253_original_document hero=pixel_locked version=%s",
        _EYE_SUPPORT_WEIGHT, _EYE_RAW_CORE_WEIGHT, _EYE_RAW_MIX, _EYE_MAX_LOCAL_SHIFT, VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V259_ENFORCE

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v259.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V259_ENFORCE = current
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V260 memory-safe ROI eye correction installed over V259", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_pixel_transfer_v260",
    "_true_face_transfer_v260",
    "_eye_roi",
    "_warp_source_roi",
]
