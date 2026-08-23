# -*- coding: utf-8 -*-
"""V258: restrict real source-pixel reinjection to an inner facial core.

Production V257 telemetry showed that V255 successfully stopped source neck/clothes/
background leakage, but a very broad ~0.91 source/target face-mask intersection plus
94% interior reinjection could still leave a soft veil / tonal mismatch around the
outer cheek, temple and face edge.

V258 is a narrow compositor-only successor:
- retain V257 native-sampling admission, <=1.90x source warp, YuNet landmarks,
  V254 target no-neck mask and V255 warped source-face hard gate;
- keep Poisson integration, but reveal it through an eroded/feathered inner-core
  support so the outer face ring remains predominantly target-scene pixels;
- confine matched real source-pixel reinjection to a still smaller detail core;
- reduce reinjection from 0.94 to an adaptive 0.89/0.88/0.87 according to mask
  coverage, shrinking the core more when the intersection is unusually broad;
- preserve PERSON-B firewall and V253 lossless original-document PNG delivery;
- fall back to the proven V257 path for every unrelated failure;
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

VERSION = "v258-inner-face-integration-2026-08-24"
_INSTALLED = False
_BASE_V257_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None

# Coverage-adaptive policy: a broad mask gets both a tighter core and less source
# reinjection.  These values intentionally stay below V256/V257's 0.94.
_REINJECT_DEFAULT = 0.89
_REINJECT_MID = 0.88
_REINJECT_HIGH = 0.87
_COVERAGE_MID = 0.86
_COVERAGE_HIGH = 0.90


def _modules():
    return v256._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _detail_reinject_for_coverage(coverage: float) -> float:
    if float(coverage) >= _COVERAGE_HIGH:
        return _REINJECT_HIGH
    if float(coverage) >= _COVERAGE_MID:
        return _REINJECT_MID
    return _REINJECT_DEFAULT


def _core_erode_fraction(coverage: float) -> float:
    """Return face-short-side erosion fraction for the Poisson visibility core."""
    if float(coverage) >= _COVERAGE_HIGH:
        return 0.075
    if float(coverage) >= _COVERAGE_MID:
        return 0.065
    return 0.055


def _elliptic_erode(mask, radius_px: int):
    import cv2

    radius_px = max(1, int(radius_px))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (radius_px * 2 + 1, radius_px * 2 + 1),
    )
    return cv2.erode(mask, kernel, iterations=1)


def _source_pixel_transfer_v258(stage1: bytes, source: bytes, model_path) -> bytes:
    """V257 geometry/sampling with target-heavy outer ring and source-only core."""
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

    # Preserve V257's native-sampling-only admission: no projected-size floor.
    if not (0.20 <= mean_scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V258 invalid face transform scale={mean_scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(
            f"V258 source face sampling too small: native_short={native_face_short:.1f}"
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
            f"V258 source/target face-mask intersection too small: pixels={area} coverage={coverage:.3f}"
        )

    matched = v253._colour_match_lab(warped, target, hard_mask)

    ys, xs = np.where(hard_mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V258 intersected face mask empty")
    clone_center = (
        int(round((int(xs.min()) + int(xs.max())) / 2.0)),
        int(round((int(ys.min()) + int(ys.max())) / 2.0)),
    )

    clone_mode = "poisson_normal"
    try:
        poisson = cv2.seamlessClone(matched, target, hard_mask, clone_center, cv2.NORMAL_CLONE)
    except Exception as exc:
        clone_mode = "feather_fallback"
        _log("AI_SELFIE_V258_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
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

    # Zone A: inner integration core.  The full hard mask remains a safety gate,
    # but the outer ring is intentionally target-heavy instead of fully Poisson.
    core_fraction = _core_erode_fraction(coverage)
    core_erode_px = max(9, min(64, int(round(face_min * core_fraction))))
    core = _elliptic_erode(hard_mask, core_erode_px)
    core_area = int((core > 80).sum())

    # Extremely narrow detections should not collapse the core; retain a minimum
    # useful interior and otherwise fall back to a milder erosion.
    if core_area < int(area * 0.30):
        core_erode_px = max(7, min(48, int(round(face_min * 0.045))))
        core = _elliptic_erode(hard_mask, core_erode_px)
        core_area = int((core > 80).sum())
    if core_area < 1200:
        raise RuntimeError(f"V258 inner core too small: pixels={core_area}")

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

    # Zone B: smaller real-source detail core.  No source reinjection is allowed
    # in the outer ring; the ring therefore inherits target-scene tone/texture.
    detail_erode_px = max(5, min(28, int(round(face_min * 0.018))))
    detail_core = _elliptic_erode(core, detail_erode_px)
    detail_sigma = max(4.0, min(12.0, face_min * 0.012))
    detail_core = cv2.GaussianBlur(detail_core, (0, 0), sigmaX=detail_sigma, sigmaY=detail_sigma)
    detail_core = cv2.min(detail_core, core)

    reinject = _detail_reinject_for_coverage(coverage)
    detail_alpha = (detail_core.astype(np.float32) / 255.0 * reinject)[:, :, None]
    final = np.clip(
        matched.astype(np.float32) * detail_alpha
        + integrated.astype(np.float32) * (1.0 - detail_alpha),
        0,
        255,
    ).astype(np.uint8)

    # PERSON-B firewall remains byte-for-byte target-owned.
    final[:, firewall_x:] = target[:, firewall_x:]

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V258 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    _log(
        "AI_SELFIE_V258_TRANSFER status=success method=yunet_inner_core_real_source_pixels "
        "source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f "
        "scale_limit=%.2f native_face_short=%.1f projected_face_short=%.1f projected_gate=false "
        "mask=target_intersect_warped_source_face_no_neck mask_pixels=%s coverage=%.3f "
        "core_pixels=%s core_erode_px=%s core_fraction=%.3f outer_ring_pixels=%s "
        "outer_ring_target_heavy=true blend=%s detail_reinject=%.2f detail_core_only=true "
        "one_pass_lanczos=true provider_bypassed=true hero_firewall_x=%s output=png bytes=%s "
        "source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh, transform_mode, sim_err, fit_err, anisotropy,
        mean_scale, v256._MAX_REAL_SOURCE_SCALE, native_face_short, projected_face_short,
        area, coverage, core_area, core_erode_px, core_fraction, outer_ring_pixels,
        clone_mode, reinject, firewall_x, len(output),
    )
    return output


async def _true_face_transfer_v258(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V258 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v258(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_inner_core_source_pixels_v258"
        return final, "opencv_yunet_inner_core_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V258_TRANSFER status=fallback_v257 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        if not callable(_BASE_TRUE_FACE_TRANSFER):
            raise
        return await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V257 then own only final PERSON-A integration/compositing."""
    global _BASE_V257_ENFORCE
    if not callable(_BASE_V257_ENFORCE):
        raise RuntimeError("V258 base V257 enforcer was not captured")

    _BASE_V257_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v258
    delivery._deliver = v253._deliver_original

    # Historical late enforcers must always return to the final V258 owner.
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
        v253, v254, v255, v256, v257,
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
            "v258-front-camera-yunet-inner-face-core-source-pixels-lossless-document"
        )
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> YuNet landmarks -> V257 native-sampling real source-pixel warp <=1.90 -> "
            "V255 target/source hard face gate + V254 no-neck -> Poisson inner-core integration with target-heavy outer ring -> "
            "adaptive 87-89% real source detail-core reinjection -> native PNG -> V253 original Telegram document; "
            "V257 fallback retained"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V258_ENFORCE status=ok base=v257 scale_limit=%.2f native_face_short_min=%.1f "
        "projected_gate=false source_gate=v255 no_neck=true integration=inner_core_target_heavy_outer_ring "
        "detail_reinject=adaptive_0.87_0.89 provider_primary=false delivery=v253_original_document "
        "hero=pixel_locked version=%s",
        v256._MAX_REAL_SOURCE_SCALE, v256._MIN_NATIVE_FACE_SHORT, VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V257_ENFORCE, _BASE_TRUE_FACE_TRANSFER

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v257.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V257_ENFORCE = current

    current(bind_generate=True)
    *_, transfer, _, _, _ = _modules()
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V258 inner-face integration compositor installed over V257", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_pixel_transfer_v258",
    "_detail_reinject_for_coverage",
    "_core_erode_fraction",
]
