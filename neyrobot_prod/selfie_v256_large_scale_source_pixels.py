# -*- coding: utf-8 -*-
"""V256: keep native source-pixel transfer active for legitimate ~1.6x face fits.

Production V255 telemetry showed a clean YuNet detection on both faces but the real
source-pixel compositor was rejected only because the similarity transform scale was
1.654, just above the historical 1.45 safety envelope. That forced V255 -> V254 ->
V253 -> V252 and reintroduced the Segmind provider path, which is exactly where the
visible eye/eyebrow pixelation came back.

V256 changes only this final PERSON-A transfer decision:
- retain YuNet landmarks, V254 geometry fit, V255 source-face gate and no-neck mask;
- allow a bounded isotropic enlargement up to 1.90 when the detected source face has
  enough native sampling density;
- keep the warp single-pass Lanczos4 (no synthetic SR, no provider, no redraw);
- slightly strengthen real matched source-pixel reinjection inside the hard face gate;
- preserve PERSON-B byte-for-byte and reuse V253 original-document delivery;
- fall back to V255 for every other failure mode.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v255_source_face_gate as v255

VERSION = "v256-large-scale-source-pixels-2026-08-22"
_INSTALLED = False
_BASE_V255_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None
_MAX_REAL_SOURCE_SCALE = 1.90
_MIN_NATIVE_FACE_SHORT = 320.0
_MIN_PROJECTED_FACE_SHORT = 520.0


def _modules():
    return v254._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _source_pixel_transfer_v256(stage1: bytes, source: bytes, model_path) -> bytes:
    """V255 face-gated compositor with a sampling-aware large-scale allowance."""
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

    if not (0.20 <= mean_scale <= _MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V256 invalid face transform scale={mean_scale:.3f}")
    if native_face_short < _MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(
            f"V256 source face sampling too small: native_short={native_face_short:.1f}"
        )
    if projected_face_short < _MIN_PROJECTED_FACE_SHORT:
        raise RuntimeError(
            f"V256 projected source face sampling too small: projected_short={projected_face_short:.1f}"
        )

    # One resampling step only.  For the observed 516px source-face short side at
    # scale 1.654 this maps ~853 effective source samples across the target face,
    # avoiding the lossy provider fallback without inventing new identity pixels.
    warped = cv2.warpAffine(
        source_im,
        matrix,
        (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    target_mask = v254._target_face_mask(target.shape, target_bbox, firewall_x)
    source_gate = v255._warp_source_face_gate(source_im.shape, source_bbox, matrix, target.shape, firewall_x)
    hard_mask = cv2.bitwise_and(target_mask, source_gate)

    target_area = int((target_mask > 80).sum())
    area = int((hard_mask > 80).sum())
    coverage = float(area) / max(1.0, float(target_area))
    if area < 3500 or coverage < 0.46:
        raise RuntimeError(
            f"V256 source/target face-mask intersection too small: pixels={area} coverage={coverage:.3f}"
        )

    matched = v253._colour_match_lab(warped, target, hard_mask)

    ys, xs = np.where(hard_mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V256 intersected face mask empty")
    clone_center = (
        int(round((int(xs.min()) + int(xs.max())) / 2.0)),
        int(round((int(ys.min()) + int(ys.max())) / 2.0)),
    )

    clone_mode = "poisson_normal"
    try:
        integrated = cv2.seamlessClone(matched, target, hard_mask, clone_center, cv2.NORMAL_CLONE)
    except Exception as exc:
        clone_mode = "feather_fallback"
        _log("AI_SELFIE_V256_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        sigma = max(6.0, min(20.0, float(min(target_bbox[2], target_bbox[3])) * 0.025))
        soft = cv2.GaussianBlur(hard_mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
        soft = cv2.min(soft, hard_mask)
        alpha = (soft.astype(np.float32) / 255.0)[:, :, None]
        integrated = np.clip(
            matched.astype(np.float32) * alpha + target.astype(np.float32) * (1.0 - alpha),
            0,
            255,
        ).astype(np.uint8)

    # Keep substantially more of the actual matched source detail in the interior.
    # This is still source pixels only, not sharpening or hallucinated restoration.
    face_min = float(min(target_bbox[2], target_bbox[3]))
    erode_px = max(11, min(55, int(round(face_min * 0.070))))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1, erode_px * 2 + 1))
    inner = cv2.erode(hard_mask, kernel, iterations=1)
    inner_sigma = max(4.0, min(12.0, face_min * 0.016))
    inner = cv2.GaussianBlur(inner, (0, 0), sigmaX=inner_sigma, sigmaY=inner_sigma)
    inner = cv2.min(inner, hard_mask)
    detail_alpha = (inner.astype(np.float32) / 255.0 * 0.94)[:, :, None]
    final = np.clip(
        matched.astype(np.float32) * detail_alpha + integrated.astype(np.float32) * (1.0 - detail_alpha),
        0,
        255,
    ).astype(np.uint8)

    final[:, firewall_x:] = target[:, firewall_x:]

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V256 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    _log(
        "AI_SELFIE_V256_TRANSFER status=success method=yunet_large_scale_real_source_pixels "
        "source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f "
        "scale_limit=%.2f native_face_short=%.1f projected_face_short=%.1f "
        "mask=target_intersect_warped_source_face_no_neck mask_pixels=%s coverage=%.3f "
        "blend=%s detail_reinject=0.94 one_pass_lanczos=true provider_bypassed=true "
        "hero_firewall_x=%s output=png bytes=%s source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh, transform_mode, sim_err, fit_err, anisotropy,
        mean_scale, _MAX_REAL_SOURCE_SCALE, native_face_short, projected_face_short,
        area, coverage, clone_mode, firewall_x, len(output),
    )
    return output


async def _true_face_transfer_v256(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V256 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v256(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_large_scale_source_pixels_v256"
        return final, "opencv_yunet_large_scale_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V256_TRANSFER status=fallback_v255 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        if not callable(_BASE_TRUE_FACE_TRANSFER):
            raise
        return await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V255 then own only the final sampling-aware PERSON-A transfer."""
    global _BASE_V255_ENFORCE
    if not callable(_BASE_V255_ENFORCE):
        raise RuntimeError("V256 base V255 enforcer was not captured")

    _BASE_V255_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v256
    delivery._deliver = v253._deliver_original

    v255.enforce_runtime = enforce_runtime
    v254.enforce_runtime = enforce_runtime
    v253.enforce_runtime = enforce_runtime
    v252.enforce_runtime = enforce_runtime
    v251.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, delivery, v241, v245, v246, v247, v249, v250, v251, v252, v253, v254, v255):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v256-front-camera-yunet-large-scale-source-pixels-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> YuNet landmarks -> sampling-aware real source-pixel warp <=1.90 -> "
            "V255 target/source hard face gate -> LAB + Poisson + 94% real source interior -> "
            "native PNG -> V253 original Telegram document; V255 fallback only"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V256_ENFORCE status=ok base=v255 scale_limit=%.2f sampling_guard=true "
        "warp=single_lanczos source_gate=v255 no_neck=true detail_reinject=0.94 "
        "provider_primary=false delivery=v253_original_document hero=pixel_locked version=%s",
        _MAX_REAL_SOURCE_SCALE, VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V255_ENFORCE, _BASE_TRUE_FACE_TRANSFER

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v255.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V255_ENFORCE = current

    current(bind_generate=True)
    *_, transfer, _, _, _ = _modules()
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V256 sampling-aware large-scale real-source compositor installed over V255", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_pixel_transfer_v256",
]
