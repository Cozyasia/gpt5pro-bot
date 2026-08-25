# -*- coding: utf-8 -*-
"""V259: protect source-eye identity after V258 face integration.

The first production V258 sample confirmed that the broad face-mask problem was
fixed: the target-heavy outer ring removed the cheek/temple veil and V258 stayed on
the real-source-pixel path.  The remaining visible defect is local to the eyes.
V258 telemetry also showed a ~19 px five-landmark similarity RMS; that is acceptable
for the whole face, but large enough to soften/ghost an eye when LAB/Poisson and the
source detail core are blended at slightly different local eye positions.

V259 is therefore an eye-only successor to V258:
- preserve the complete V258 two-zone compositor, V255 source hard gate, V254
  no-neck target mask, V257 native sampling guard and V253 lossless delivery;
- compute each source-eye residual after the global five-point transform;
- locally translate each already-warped source eye so its YuNet eye landmark lands
  exactly on the generated target eye landmark (bounded correction only);
- use a feathered support mask for matched source pixels and a tighter ocular core
  that strongly restores RAW real source pixels after LAB/Poisson;
- intersect every ocular mask with the V258 detail core and hard face gate;
- keep PERSON-B byte-for-byte target-owned;
- fall back to the proven V258 path on any V259-specific failure;
- add no Telegram callback, payment, UX, scene-owner or provider handler.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v255_source_face_gate as v255
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v257_native_sampling_guard as v257
from neyrobot_prod import selfie_v258_inner_face_integration as v258

VERSION = "v259-eye-landmark-protection-2026-08-26"
_INSTALLED = False
_BASE_V258_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None

# Eye-only policy.  Support restores the globally colour-matched source eye region;
# the tighter core restores mostly RAW source pixels so iris/pupil/eyelid contrast
# is not flattened by the broad LAB statistics or Poisson solution.
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


def _eye_mask(shape, center, axes, *, sigma: float, gate):
    import cv2
    import numpy as np

    h, w = int(shape[0]), int(shape[1])
    mask = np.zeros((h, w), dtype=np.uint8)
    cx = max(0, min(w - 1, int(round(float(center[0])))))
    cy = max(0, min(h - 1, int(round(float(center[1])))))
    ax = max(4, int(round(float(axes[0]))))
    ay = max(3, int(round(float(axes[1]))))
    cv2.ellipse(mask, (cx, cy), (ax, ay), 0.0, 0.0, 360.0, 255, -1, lineType=cv2.LINE_AA)
    if float(sigma) > 0.0:
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=float(sigma), sigmaY=float(sigma))
    mask = cv2.min(mask, gate)
    return mask


def _shift_frame(frame, dx: float, dy: float):
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    affine = np.asarray([[1.0, 0.0, float(dx)], [0.0, 1.0, float(dy)]], dtype=np.float32)
    return cv2.warpAffine(
        frame,
        affine,
        (w, h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _source_pixel_transfer_v259(stage1: bytes, source: bytes, model_path) -> bytes:
    """V258 compositor plus bounded per-eye landmark correction/protection."""
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    sh, sw = source_im.shape[:2]

    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    left_target = target[:, :firewall_x].copy()
    source_bbox, source_pts = v253._yunet_face(source_im, model_path, label="source_photo3")
    target_bbox, target_pts = v253._yunet_face(left_target, model_path, label="target_person_a")

    matrix, transform_mode, sim_err, fit_err, anisotropy = v254._choose_transform(source_pts, target_pts)
    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    mean_scale = math.sqrt(abs(det)) if det != 0.0 else 0.0

    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = float(min(sfw, sfh))
    projected_face_short = native_face_short * mean_scale

    if not (0.20 <= mean_scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V259 invalid face transform scale={mean_scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(
            f"V259 source face sampling too small: native_short={native_face_short:.1f}"
        )

    warped = cv2.warpAffine(
        source_im,
        matrix,
        (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    target_mask = v254._target_face_mask(target.shape, target_bbox, firewall_x)
    source_gate = v255._warp_source_face_gate(
        source_im.shape,
        source_bbox,
        matrix,
        target.shape,
        firewall_x,
    )
    hard_mask = cv2.bitwise_and(target_mask, source_gate)

    target_area = int((target_mask > 80).sum())
    area = int((hard_mask > 80).sum())
    coverage = float(area) / max(1.0, float(target_area))
    if area < 3500 or coverage < 0.46:
        raise RuntimeError(
            f"V259 source/target face-mask intersection too small: pixels={area} coverage={coverage:.3f}"
        )

    matched = v253._colour_match_lab(warped, target, hard_mask)

    ys, xs = np.where(hard_mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V259 intersected face mask empty")
    clone_center = (
        int(round((int(xs.min()) + int(xs.max())) / 2.0)),
        int(round((int(ys.min()) + int(ys.max())) / 2.0)),
    )

    clone_mode = "poisson_normal"
    try:
        poisson = cv2.seamlessClone(matched, target, hard_mask, clone_center, cv2.NORMAL_CLONE)
    except Exception as exc:
        clone_mode = "feather_fallback"
        _log("AI_SELFIE_V259_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        sigma = max(6.0, min(20.0, float(min(target_bbox[2], target_bbox[3])) * 0.025))
        soft = cv2.GaussianBlur(hard_mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
        soft = cv2.min(soft, hard_mask)
        alpha = (soft.astype(np.float32) / 255.0)[:, :, None]
        poisson = np.clip(
            matched.astype(np.float32) * alpha + target.astype(np.float32) * (1.0 - alpha),
            0,
            255,
        ).astype(np.uint8)

    face_min = float(min(target_bbox[2], target_bbox[3]))

    # Preserve V258 Zone A exactly: inner Poisson integration with a target-heavy
    # outer ring, all clipped by the hard source/target face intersection.
    core_fraction = v258._core_erode_fraction(coverage)
    core_erode_px = max(9, min(64, int(round(face_min * core_fraction))))
    core = v258._elliptic_erode(hard_mask, core_erode_px)
    core_area = int((core > 80).sum())
    if core_area < int(area * 0.30):
        core_erode_px = max(7, min(48, int(round(face_min * 0.045))))
        core = v258._elliptic_erode(hard_mask, core_erode_px)
        core_area = int((core > 80).sum())
    if core_area < 1200:
        raise RuntimeError(f"V259 inner core too small: pixels={core_area}")

    outer_ring_pixels = max(0, area - core_area)
    edge_sigma = max(7.0, min(24.0, face_min * 0.030))
    integration_support = cv2.GaussianBlur(core, (0, 0), sigmaX=edge_sigma, sigmaY=edge_sigma)
    integration_support = cv2.min(integration_support, hard_mask)
    integration_alpha = (integration_support.astype(np.float32) / 255.0)[:, :, None]
    integrated = np.clip(
        poisson.astype(np.float32) * integration_alpha
        + target.astype(np.float32) * (1.0 - integration_alpha),
        0,
        255,
    ).astype(np.uint8)

    # Preserve V258 Zone B: broad identity/detail core stays adaptive 0.87-0.89.
    detail_erode_px = max(5, min(28, int(round(face_min * 0.018))))
    detail_core = v258._elliptic_erode(core, detail_erode_px)
    detail_sigma = max(4.0, min(12.0, face_min * 0.012))
    detail_core = cv2.GaussianBlur(detail_core, (0, 0), sigmaX=detail_sigma, sigmaY=detail_sigma)
    detail_core = cv2.min(detail_core, core)

    reinject = v258._detail_reinject_for_coverage(coverage)
    detail_alpha = (detail_core.astype(np.float32) / 255.0 * reinject)[:, :, None]
    final = np.clip(
        matched.astype(np.float32) * detail_alpha
        + integrated.astype(np.float32) * (1.0 - detail_alpha),
        0,
        255,
    ).astype(np.uint8)

    # V259 eye stage. YuNet order is right eye, left eye, nose, right mouth, left
    # mouth.  The global similarity transform is retained for the face; only the
    # two eye patches receive the residual translation that the global fit cannot
    # satisfy exactly.
    projected_pts = _project_points(matrix, source_pts)
    eye_residuals = []
    eye_shifts = []
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

    for eye_index in (0, 1):
        residual = np.asarray(target_pts[eye_index], dtype=np.float32) - np.asarray(
            projected_pts[eye_index], dtype=np.float32
        )
        residual_norm = float(np.linalg.norm(residual))
        eye_residuals.append(residual_norm)
        if residual_norm > _EYE_MAX_LOCAL_SHIFT:
            raise RuntimeError(
                f"V259 eye residual too large: eye={eye_index} residual={residual_norm:.2f}px"
            )

        dx, dy = float(residual[0]), float(residual[1])
        eye_shifts.append((dx, dy))
        shifted_matched = _shift_frame(matched, dx, dy)
        shifted_raw = _shift_frame(warped, dx, dy)

        support_mask = _eye_mask(
            target.shape,
            target_pts[eye_index],
            support_axes,
            sigma=support_sigma,
            gate=detail_core,
        )
        support_alpha = (
            support_mask.astype(np.float32) / 255.0 * _EYE_SUPPORT_WEIGHT
        )[:, :, None]
        final = np.clip(
            shifted_matched.astype(np.float32) * support_alpha
            + final.astype(np.float32) * (1.0 - support_alpha),
            0,
            255,
        ).astype(np.uint8)

        raw_mask = _eye_mask(
            target.shape,
            target_pts[eye_index],
            raw_axes,
            sigma=raw_sigma,
            gate=detail_core,
        )
        raw_alpha = (
            raw_mask.astype(np.float32) / 255.0 * _EYE_RAW_CORE_WEIGHT
        )[:, :, None]
        ocular_source = np.clip(
            shifted_raw.astype(np.float32) * _EYE_RAW_MIX
            + shifted_matched.astype(np.float32) * (1.0 - _EYE_RAW_MIX),
            0,
            255,
        ).astype(np.uint8)
        final = np.clip(
            ocular_source.astype(np.float32) * raw_alpha
            + final.astype(np.float32) * (1.0 - raw_alpha),
            0,
            255,
        ).astype(np.uint8)

    # PERSON-B firewall remains byte-for-byte target-owned after all eye work.
    final[:, firewall_x:] = target[:, firewall_x:]

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V259 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    _log(
        "AI_SELFIE_V259_TRANSFER status=success method=yunet_inner_core_eye_landmark_protected_source_pixels "
        "source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f "
        "scale_limit=%.2f native_face_short=%.1f projected_face_short=%.1f projected_gate=false "
        "mask=target_intersect_warped_source_face_no_neck mask_pixels=%s coverage=%.3f "
        "core_pixels=%s core_erode_px=%s core_fraction=%.3f outer_ring_pixels=%s "
        "outer_ring_target_heavy=true blend=%s detail_reinject=%.2f detail_core_only=true "
        "eye_landmark_local_correction=true eye0_residual=%.2f eye1_residual=%.2f "
        "eye0_shift=%.2f,%.2f eye1_shift=%.2f,%.2f eye_support=%.2f eye_raw_core=%.2f "
        "eye_raw_mix=%.2f eye_masks_hard_gated=true one_pass_lanczos=true provider_bypassed=true "
        "hero_firewall_x=%s output=png bytes=%s source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh, transform_mode, sim_err, fit_err, anisotropy,
        mean_scale, v256._MAX_REAL_SOURCE_SCALE, native_face_short, projected_face_short,
        area, coverage, core_area, core_erode_px, core_fraction, outer_ring_pixels,
        clone_mode, reinject,
        eye_residuals[0], eye_residuals[1],
        eye_shifts[0][0], eye_shifts[0][1], eye_shifts[1][0], eye_shifts[1][1],
        _EYE_SUPPORT_WEIGHT, _EYE_RAW_CORE_WEIGHT, _EYE_RAW_MIX,
        firewall_x, len(output),
    )
    return output


async def _true_face_transfer_v259(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V259 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v259(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_eye_landmark_source_pixels_v259"
        return final, "opencv_yunet_eye_landmark_protected_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V259_TRANSFER status=fallback_v258 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        if not callable(_BASE_TRUE_FACE_TRANSFER):
            raise
        return await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V258, then own only the final eye-protected PERSON-A transfer."""
    global _BASE_V258_ENFORCE
    if not callable(_BASE_V258_ENFORCE):
        raise RuntimeError("V259 base V258 enforcer was not captured")

    _BASE_V258_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v259
    delivery._deliver = v253._deliver_original

    # Every historical late enforcer returns to the final V259 owner.
    v258.enforce_runtime = enforce_runtime
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
        v253, v254, v255, v256, v257, v258,
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
            "v259-front-camera-yunet-inner-face-eye-landmark-source-pixels-lossless-document"
        )
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> YuNet landmarks -> V257 native-sampling real source-pixel warp <=1.90 -> "
            "V255 target/source hard face gate + V254 no-neck -> V258 target-heavy outer ring + adaptive detail core -> "
            "V259 bounded per-eye landmark correction + protected raw-source ocular core -> native PNG -> "
            "V253 original Telegram document; V258 fallback retained"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V259_ENFORCE status=ok base=v258 scale_limit=%.2f native_face_short_min=%.1f "
        "projected_gate=false source_gate=v255 no_neck=true integration=v258_inner_core_target_heavy_outer_ring "
        "detail_reinject=adaptive_0.87_0.89 eye_landmark_local_correction=true eye_support=%.2f "
        "eye_raw_core=%.2f eye_raw_mix=%.2f eye_shift_limit=%.1f provider_primary=false "
        "delivery=v253_original_document hero=pixel_locked version=%s",
        v256._MAX_REAL_SOURCE_SCALE, v256._MIN_NATIVE_FACE_SHORT,
        _EYE_SUPPORT_WEIGHT, _EYE_RAW_CORE_WEIGHT, _EYE_RAW_MIX, _EYE_MAX_LOCAL_SHIFT, VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V258_ENFORCE, _BASE_TRUE_FACE_TRANSFER

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v258.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V258_ENFORCE = current

    current(bind_generate=True)
    *_, transfer, _, _, _ = _modules()
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V259 eye landmark protection installed over V258", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_pixel_transfer_v259",
    "_project_points",
    "_eye_mask",
]
