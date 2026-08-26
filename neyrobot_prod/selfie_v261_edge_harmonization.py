# -*- coding: utf-8 -*-
"""V261: remove the visible face-mask oval without softening identity detail.

Production V260 is stable and preserves the source eyes, but the successful sample
still shows a low-frequency oval around PERSON-A.  Telemetry proves the eye ROIs are
not the cause; the visible boundary comes from the V258 hard face intersection and
its outer integration ring.

V261 keeps V260 byte-for-byte as the identity/eye base and adds one final, compact
face-ROI operation only:
- recompute the same V255 source/target hard face gate;
- use distance-to-boundary, not another ellipse, for the final transition;
- harmonize only low-frequency LAB tone near the boundary;
- cross-fade to the untouched Gemini target over a narrow edge band;
- leave the central real-source face and V260 eye ROIs at full strength;
- never allocate full-frame float32 working buffers;
- keep PERSON-B outside the firewall untouched;
- if V261 edge work fails, return the already-successful V260 PNG.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v255_source_face_gate as v255
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v257_native_sampling_guard as v257
from neyrobot_prod import selfie_v258_inner_face_integration as v258
from neyrobot_prod import selfie_v259_eye_landmark_protection as v259
from neyrobot_prod import selfie_v260_eye_roi_memory_safe as v260

VERSION = "v261-edge-harmonization-2026-08-26"
_INSTALLED = False
_BASE_V260_ENFORCE = None

# Boundary-only policy.  The successful V260 sample had target face short side 511px.
# This yields ~38px of identity-to-target transition: wide enough to eliminate the
# visible oval, small enough to leave eyes/nose/mouth and most cheek texture intact.
_EDGE_FEATHER_FRACTION = 0.075
_EDGE_FEATHER_MIN = 24.0
_EDGE_FEATHER_MAX = 52.0
_TONE_SIGMA_FRACTION = 0.028
_TONE_SIGMA_MIN = 8.0
_TONE_SIGMA_MAX = 18.0
_TONE_STRENGTH = 0.62
_L_CLAMP = 8.0
_AB_CLAMP = 5.0


def _modules():
    return v256._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _smoothstep01(values):
    import numpy as np

    t = np.clip(values, 0.0, 1.0).astype(np.float32, copy=False)
    return t * t * (3.0 - 2.0 * t)


def _edge_harmonize_v261(stage1: bytes, source: bytes, v260_png: bytes, model_path) -> bytes:
    """Blend only the hard face boundary in a compact ROI; central source pixels stay intact."""
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    final = v253._decode_bgr(v260_png)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    if final.shape[:2] != (th, tw):
        raise RuntimeError(f"V261 stage/final size mismatch target={tw}x{th} final={final.shape[1]}x{final.shape[0]}")

    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    source_bbox, source_pts = v253._yunet_face(source_im, model_path, label="source_photo3_v261")
    target_bbox, target_pts = v253._yunet_face(
        target[:, :firewall_x], model_path, label="target_person_a_v261"
    )
    matrix, transform_mode, sim_err, fit_err, anisotropy = v254._choose_transform(source_pts, target_pts)

    target_mask = v254._target_face_mask(target.shape, target_bbox, firewall_x)
    source_gate = v255._warp_source_face_gate(
        source_im.shape,
        source_bbox,
        matrix,
        target.shape,
        firewall_x,
    )
    hard_mask = cv2.bitwise_and(target_mask, source_gate)
    ys, xs = np.where(hard_mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V261 hard face mask empty")

    face_min = float(min(target_bbox[2], target_bbox[3]))
    feather_px = max(_EDGE_FEATHER_MIN, min(_EDGE_FEATHER_MAX, face_min * _EDGE_FEATHER_FRACTION))
    tone_sigma = max(_TONE_SIGMA_MIN, min(_TONE_SIGMA_MAX, face_min * _TONE_SIGMA_FRACTION))
    pad = int(round(feather_px + 3.0 * tone_sigma + 8.0))

    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(firewall_x, int(xs.max()) + pad + 1)
    y1 = min(th, int(ys.max()) + pad + 1)
    if x1 - x0 < 80 or y1 - y0 < 80:
        raise RuntimeError(f"V261 face ROI too small: {x1-x0}x{y1-y0}")

    mask_roi = hard_mask[y0:y1, x0:x1]
    binary = (mask_roi > 80).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)

    # alpha=0 at the old hard boundary, alpha=1 after feather_px.  This reaches
    # exactly zero before the source/target mask ends, so the old oval edge cannot
    # remain as a low-amplitude discontinuity.
    alpha = _smoothstep01(distance / max(1.0, feather_px))
    alpha *= binary.astype(np.float32)

    target_roi = target[y0:y1, x0:x1]
    final_roi = final[y0:y1, x0:x1]

    # Low-frequency LAB correction only in the transition band.  We adjust smooth
    # illumination/chroma, never blur the final source texture itself.
    target_lab = cv2.cvtColor(target_roi, cv2.COLOR_BGR2LAB)
    final_lab = cv2.cvtColor(final_roi, cv2.COLOR_BGR2LAB)
    target_low = cv2.GaussianBlur(target_lab, (0, 0), sigmaX=tone_sigma, sigmaY=tone_sigma)
    final_low = cv2.GaussianBlur(final_lab, (0, 0), sigmaX=tone_sigma, sigmaY=tone_sigma)
    delta = target_low.astype(np.float32) - final_low.astype(np.float32)
    delta[:, :, 0] = np.clip(delta[:, :, 0], -_L_CLAMP, _L_CLAMP)
    delta[:, :, 1] = np.clip(delta[:, :, 1], -_AB_CLAMP, _AB_CLAMP)
    delta[:, :, 2] = np.clip(delta[:, :, 2], -_AB_CLAMP, _AB_CLAMP)

    edge_weight = ((1.0 - alpha) ** 0.72) * binary.astype(np.float32) * _TONE_STRENGTH
    harmonized_lab = np.clip(
        final_lab.astype(np.float32) + delta * edge_weight[:, :, None],
        0,
        255,
    ).astype(np.uint8)
    harmonized = cv2.cvtColor(harmonized_lab, cv2.COLOR_LAB2BGR)

    # Identity remains 100% V260 in the core.  Only the boundary transitions back
    # to the original stage-1 scene face so skin illumination and contour become
    # continuous.  No source pixels can leak outside the old hard gate.
    a3 = alpha[:, :, None]
    blended = np.clip(
        harmonized.astype(np.float32) * a3
        + target_roi.astype(np.float32) * (1.0 - a3),
        0,
        255,
    ).astype(np.uint8)
    final[y0:y1, x0:x1] = blended

    # PERSON-B is protected byte-for-byte after the operation as an extra firewall.
    final[:, firewall_x:] = target[:, firewall_x:]

    core_pixels = int((distance >= feather_px).sum())
    transition_pixels = int(((distance > 0.0) & (distance < feather_px)).sum())
    mask_pixels = int(binary.sum())

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V261 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    _log(
        "AI_SELFIE_V261_EDGE status=success method=distance_feather_lab_edge_harmonize "
        "transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f "
        "face_short=%.1f mask_pixels=%s transition_pixels=%s source_core_pixels=%s "
        "feather_px=%.1f tone_sigma=%.1f tone_strength=%.2f luma_clamp=%.1f ab_clamp=%.1f "
        "roi=%sx%s edge_target_blend=true central_source_pixels_untouched=true "
        "full_frame_float_blend=false person_b_untouched=true output=png bytes=%s",
        transform_mode, sim_err, fit_err, anisotropy,
        face_min, mask_pixels, transition_pixels, core_pixels,
        feather_px, tone_sigma, _TONE_STRENGTH, _L_CLAMP, _AB_CLAMP,
        x1 - x0, y1 - y0, len(output),
    )
    return output


def _source_pixel_transfer_v261(stage1: bytes, source: bytes, model_path) -> bytes:
    """Use V260 as the stable identity base, then suppress only its visible edge oval."""
    base_png = v260._source_pixel_transfer_v260(bytes(stage1 or b""), bytes(source or b""), model_path)
    _log("AI_SELFIE_V261_BASE status=success base=v260 bytes=%s", len(base_png))
    try:
        return _edge_harmonize_v261(stage1, source, base_png, model_path)
    except Exception as exc:
        _log(
            "AI_SELFIE_V261_EDGE status=fallback_v260 reason=%s:%s",
            type(exc).__name__, str(exc)[:300],
        )
        return base_png


async def _true_face_transfer_v261(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V261 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v261(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_v260_eye_roi_v261_edge_harmonized"
        return final, "opencv_yunet_v260_eye_roi_edge_harmonized_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V261_TRANSFER status=fallback_v260 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        return await v260._true_face_transfer_v260(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V260, then own only the final memory-safe edge harmonization."""
    global _BASE_V260_ENFORCE
    if not callable(_BASE_V260_ENFORCE):
        raise RuntimeError("V261 base V260 enforcer was not captured")

    _BASE_V260_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v261
    delivery._deliver = v253._deliver_original

    # Prevent any historical late enforcer from restoring an older transfer owner.
    v260.enforce_runtime = enforce_runtime
    v259.enforce_runtime = enforce_runtime
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
        v253, v254, v255, v256, v257, v258, v259, v260,
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
            "v261-front-camera-v260-eye-roi-distance-edge-harmonized-source-pixels-lossless-document"
        )
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> V260 stable V258 source-pixel face + ROI eye correction -> "
            "V261 compact distance-feather LAB edge harmonization -> native PNG -> "
            "V253 original Telegram document; V260 fallback retained"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V261_ENFORCE status=ok base=v260 eye_processing=roi_only "
        "edge_harmonization=distance_feather_lab_roi feather_fraction=%.3f feather_range=%.0f_%.0f "
        "tone_strength=%.2f full_frame_float_blend=false source_gate=v255 no_neck=true "
        "delivery=v253_original_document hero=pixel_locked version=%s",
        _EDGE_FEATHER_FRACTION, _EDGE_FEATHER_MIN, _EDGE_FEATHER_MAX, _TONE_STRENGTH, VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V260_ENFORCE

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v260.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V260_ENFORCE = current
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V261 face-edge harmonization installed over V260", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_pixel_transfer_v261",
    "_true_face_transfer_v261",
    "_edge_harmonize_v261",
]
