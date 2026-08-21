# -*- coding: utf-8 -*-
"""V255: intersect the V254 target mask with a warped real-source face gate.

Codex review of V254 found one remaining edge case: the V254 target-space face
mask is conservative, but the warped image still contains the entire source
photo. When bbox-to-landmark proportions differ, a pixel inside the target
face ellipse can originate outside the detected source face (neck, shirt, hair
or reflected border).

V255 changes only the PERSON-A compositor:
- V254 stage-1 geometry fit and bounded landmark transform are unchanged;
- a conservative face-only mask is built around the detected source bbox;
- that source mask is warped with the exact same affine matrix as the pixels;
- the final clone mask is the intersection of V254's target no-neck mask and
  the warped source-face gate;
- Poisson boundary integration, 88% real-source interior detail, PERSON-B
  firewall and V253 lossless original-document delivery are unchanged;
- V254 is the immediate fallback if the intersection is implausibly small.

No new provider, callback, payment or scene owner is introduced.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254

VERSION = "v255-source-face-gate-lossless-2026-08-22"
_INSTALLED = False
_BASE_V254_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None


def _modules():
    return v254._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _source_face_mask(shape, bbox):
    """Conservative SOURCE-space skin/feature gate; excludes neck/shirt/background."""
    import cv2
    import numpy as np

    h, w = int(shape[0]), int(shape[1])
    x, y, fw, fh = [float(v) for v in bbox]
    mask = np.zeros((h, w), dtype=np.uint8)

    center = (int(round(x + fw * 0.50)), int(round(y + fh * 0.49)))
    axes = (
        max(12, int(round(fw * 0.40))),
        max(12, int(round(fh * 0.42))),
    )
    cv2.ellipse(mask, center, axes, 0.0, 0.0, 360.0, 255, thickness=-1, lineType=cv2.LINE_AA)

    # Do not trust YuNet bbox extremities: keep central face and jaw, exclude
    # upper hair/background and the lower neck/shirt tail.
    top = max(0, int(round(y + fh * 0.060)))
    bottom = min(h, int(round(y + fh * 0.885)))
    left = max(0, int(round(x + fw * 0.070)))
    right = min(w, int(round(x + fw * 0.930)))
    mask[:top, :] = 0
    mask[bottom:, :] = 0
    mask[:, :left] = 0
    mask[:, right:] = 0
    return mask


def _warp_source_face_gate(source_shape, source_bbox, matrix, target_shape, firewall_x: int):
    """Warp source face-only mask with the exact pixel transform."""
    import cv2

    th, tw = int(target_shape[0]), int(target_shape[1])
    source_mask = _source_face_mask(source_shape, source_bbox)
    warped_source_mask = cv2.warpAffine(
        source_mask,
        matrix,
        (tw, th),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    warped_source_mask[:, max(0, min(tw, int(firewall_x))):] = 0

    # Hard gate removes antialiased transform fringes that may sample just
    # outside the conservative source face.
    _, source_gate = cv2.threshold(warped_source_mask, 96, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    source_gate = cv2.erode(source_gate, kernel, iterations=1)
    return source_gate


def _source_pixel_transfer_v255(stage1: bytes, source: bytes, model_path) -> bytes:
    """V254 compositor with target mask intersected with warped source-face gate."""
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
    if not (0.20 <= mean_scale <= 1.45):
        raise RuntimeError(f"V255 invalid face transform scale={mean_scale:.3f}")

    warped = cv2.warpAffine(
        source_im,
        matrix,
        (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    target_mask = v254._target_face_mask(target.shape, target_bbox, firewall_x)
    source_gate = _warp_source_face_gate(source_im.shape, source_bbox, matrix, target.shape, firewall_x)
    hard_mask = cv2.bitwise_and(target_mask, source_gate)

    target_area = int((target_mask > 80).sum())
    area = int((hard_mask > 80).sum())
    coverage = float(area) / max(1.0, float(target_area))
    if area < 3500 or coverage < 0.50:
        raise RuntimeError(
            f"V255 source/target face-mask intersection too small: pixels={area} coverage={coverage:.3f}"
        )

    matched = v253._colour_match_lab(warped, target, hard_mask)

    ys, xs = np.where(hard_mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V255 intersected face mask empty")
    clone_center = (
        int(round((int(xs.min()) + int(xs.max())) / 2.0)),
        int(round((int(ys.min()) + int(ys.max())) / 2.0)),
    )

    clone_mode = "poisson_normal"
    try:
        integrated = cv2.seamlessClone(matched, target, hard_mask, clone_center, cv2.NORMAL_CLONE)
    except Exception as exc:
        clone_mode = "feather_fallback"
        _log("AI_SELFIE_V255_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        sigma = max(6.0, min(20.0, float(min(target_bbox[2], target_bbox[3])) * 0.025))
        soft = cv2.GaussianBlur(hard_mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
        alpha = (soft.astype(np.float32) / 255.0)[:, :, None]
        integrated = np.clip(
            matched.astype(np.float32) * alpha + target.astype(np.float32) * (1.0 - alpha),
            0,
            255,
        ).astype(np.uint8)

    # Preserve real source micro-detail only well inside the intersected safe
    # face region; no source pixel outside source_gate can be reintroduced.
    face_min = float(min(target_bbox[2], target_bbox[3]))
    erode_px = max(11, min(55, int(round(face_min * 0.075))))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1, erode_px * 2 + 1))
    inner = cv2.erode(hard_mask, kernel, iterations=1)
    inner_sigma = max(4.0, min(14.0, face_min * 0.018))
    inner = cv2.GaussianBlur(inner, (0, 0), sigmaX=inner_sigma, sigmaY=inner_sigma)
    detail_alpha = (inner.astype(np.float32) / 255.0 * 0.88)[:, :, None]
    final = np.clip(
        matched.astype(np.float32) * detail_alpha + integrated.astype(np.float32) * (1.0 - detail_alpha),
        0,
        255,
    ).astype(np.uint8)

    # PERSON-B is restored byte-for-byte from the untouched Gemini target.
    final[:, firewall_x:] = target[:, firewall_x:]

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V255 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    _log(
        "AI_SELFIE_V255_TRANSFER status=success method=yunet_landmark_fit_source_gate_intersection "
        "source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f "
        "mask=target_intersect_warped_source_face_no_neck mask_pixels=%s "
        "source_gate_coverage=%.3f blend=%s detail_reinject=0.88 hero_firewall_x=%s "
        "output=png bytes=%s source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh, transform_mode, sim_err, fit_err, anisotropy,
        mean_scale, area, coverage, clone_mode, firewall_x, len(output),
    )
    return output


async def _true_face_transfer_v255(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V255 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v255(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_source_face_gate_v255"
        return final, "opencv_yunet_landmark_fit_source_gate_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V255_TRANSFER status=fallback_v254 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        if not callable(_BASE_TRUE_FACE_TRANSFER):
            raise
        return await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V254, then own only the final safe PERSON-A pixel transfer."""
    global _BASE_V254_ENFORCE
    if not callable(_BASE_V254_ENFORCE):
        raise RuntimeError("V255 base V254 enforcer was not captured")

    _BASE_V254_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v255
    delivery._deliver = v253._deliver_original

    # Historical late enforcers always return to this final V255 transfer owner.
    v254.enforce_runtime = enforce_runtime
    v253.enforce_runtime = enforce_runtime
    v252.enforce_runtime = enforce_runtime
    v251.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, delivery, v241, v245, v246, v247, v249, v250, v251, v252, v253, v254):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v255-front-camera-yunet-landmark-fit-source-gate-seamless-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V254 geometry-fit scaffold -> YuNet bounded transform -> "
            "V254 target no-neck mask INTERSECT warped conservative source-face gate -> "
            "LAB match + Poisson boundary + real source-detail interior -> "
            "native PNG -> V253 original Telegram document; V254 fallback only"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V255_ENFORCE status=ok base=v254 source_gate=warped_detected_face "
        "mask=target_intersect_source_face no_neck=true landmarks=5 "
        "blend=poisson_plus_source_interior source_pixels=true faceswap_primary=false "
        "fallback=v254 delivery=v253_original_document hero=pixel_locked version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V254_ENFORCE, _BASE_TRUE_FACE_TRANSFER

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v254.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V254_ENFORCE = current

    # Freeze V254 as the immediate fallback, including its proven V253 transport.
    current(bind_generate=True)
    *_, transfer, _, _, _ = _modules()
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V255 warped source-face gate installed over V254 compositor", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_face_mask",
    "_warp_source_face_gate",
    "_source_pixel_transfer_v255",
]
