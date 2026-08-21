# -*- coding: utf-8 -*-
"""V254: keep V253 native source pixels, fix pasted-face geometry and neck bleed.

Production V253 proved that the previous softness was no longer a generation or
Telegram-delivery problem: YuNet succeeded, the real source pixels were transferred,
and the original 1856x2304 PNG was delivered byte-for-byte.  The remaining defect is
compositing quality.  A single similarity warp plus a source-space oval can leave a
paper-cut face, inherit pixels below the real face (neck/shirt), and expose geometry
mismatch between Gemini's temporary PERSON-A head and the authoritative photo #3.

V254 changes only PERSON-A fit/compositing:
- Gemini stage 1 is told that PERSON-A geometry/age/head proportions are a compositing
  scaffold and therefore must follow the source crop closely;
- YuNet's five landmarks still remain the deterministic anchors;
- a bounded full affine transform is used only when it materially improves landmark
  fit without excessive anisotropic distortion; otherwise V253 similarity is kept;
- the blend mask is defined in TARGET coordinates and stops above the neck;
- OpenCV Poisson seamlessClone integrates illumination/edges at the boundary;
- a strongly eroded interior mask re-injects the matched real source pixels so eyes,
  nose, mouth and skin micro-detail remain source-authentic rather than blurred;
- PERSON-B remains behind the same hard left-side firewall;
- V253 original-document lossless delivery is reused unchanged;
- V253 remains the immediate fallback if this refined compositor cannot run.

No Telegram callback/payment/scene owner is added or replaced.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253

VERSION = "v254-landmark-fit-seamless-source-2026-08-22"
_INSTALLED = False
_BASE_V253_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None
_BASE_STAGE1_PROMPT = None


def _modules():
    return v253._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _stage1_prompt_v254(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    """Make Gemini's temporary PERSON-A a geometry-compatible compositing scaffold."""
    if not callable(_BASE_STAGE1_PROMPT):
        raise RuntimeError("V254 base stage-1 prompt unavailable")
    base = _BASE_STAGE1_PROMPT(name, scene, shot_label, has_scene_image, source_photo_no)
    return base + (
        " V254 COMPOSITING FIT LOCK — PERSON A is not disposable in GEOMETRY. "
        "The supplied user face/expression crop is also the authoritative scaffold for age, head width/height ratio, "
        "forehead height, eye spacing, nose placement, mouth placement, cheek width, jaw width, chin position, hairline, "
        "near-frontal head angle and camera-distance facial proportions. Match those proportions closely before compositing. "
        "Do not make PERSON A younger/older, narrower/wider, rounder/longer, prettier, more symmetrical or more stylized than the crop. "
        "Keep the full face well inside the frame with clean unobstructed skin boundary; no hand, glass, hair strand or object crossing the face. "
        "Texture identity will come from the real source pixels, but the generated head underneath must be geometrically compatible with them."
    )


def _apply_affine(matrix, pts):
    import numpy as np

    pts = np.asarray(pts, dtype=np.float32)
    ones = np.ones((pts.shape[0], 1), dtype=np.float32)
    hom = np.concatenate([pts, ones], axis=1)
    return hom @ np.asarray(matrix, dtype=np.float32).T


def _landmark_rms(matrix, source_pts, target_pts) -> float:
    import numpy as np

    pred = _apply_affine(matrix, source_pts)
    dst = np.asarray(target_pts, dtype=np.float32)
    return float(np.sqrt(np.mean(np.sum((pred - dst) ** 2, axis=1))))


def _choose_transform(source_pts, target_pts):
    """Choose similarity unless a safe affine fit clearly reduces landmark error."""
    import cv2
    import numpy as np

    src = np.asarray(source_pts, dtype=np.float32)
    dst = np.asarray(target_pts, dtype=np.float32)

    similarity, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if similarity is None:
        raise RuntimeError("V254 could not estimate similarity transform")
    sim_err = _landmark_rms(similarity, src, dst)

    chosen = similarity
    mode = "similarity"
    chosen_err = sim_err
    anisotropy = 1.0

    affine, _ = cv2.estimateAffine2D(src, dst, method=cv2.LMEDS)
    if affine is not None:
        linear = np.asarray(affine[:, :2], dtype=np.float64)
        det = float(np.linalg.det(linear))
        singular = np.linalg.svd(linear, compute_uv=False)
        min_sv = max(1e-8, float(min(singular)))
        max_sv = float(max(singular))
        candidate_aniso = max_sv / min_sv
        aff_err = _landmark_rms(affine, src, dst)

        # General affine is allowed only as a small geometry-fit correction.  It
        # must preserve orientation, stay within V253's scale envelope, and make
        # the five actual landmarks materially more accurate.
        mean_scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
        safe = (
            det > 0.0
            and 0.20 <= mean_scale <= 1.45
            and candidate_aniso <= 1.14
            and aff_err + 0.75 < sim_err * 0.88
        )
        if safe:
            chosen = affine
            mode = "bounded_affine"
            chosen_err = aff_err
            anisotropy = candidate_aniso

    return chosen, mode, float(sim_err), float(chosen_err), float(anisotropy)


def _target_face_mask(shape, bbox, firewall_x: int):
    """Face-only TARGET-space mask: never includes source neck, shirt or background."""
    import cv2
    import numpy as np

    h, w = int(shape[0]), int(shape[1])
    x, y, fw, fh = [float(v) for v in bbox]
    mask = np.zeros((h, w), dtype=np.uint8)

    center = (int(round(x + fw * 0.50)), int(round(y + fh * 0.49)))
    axes = (
        max(12, int(round(fw * 0.415))),
        max(12, int(round(fh * 0.435))),
    )
    cv2.ellipse(mask, center, axes, 0.0, 0.0, 360.0, 255, thickness=-1, lineType=cv2.LINE_AA)

    # YuNet's bbox can extend into chin/neck.  Keep the jaw/chin, but hard-stop
    # before the lower bbox tail where V253 could import neck/shirt pixels.
    top = max(0, int(round(y + fh * 0.055)))
    bottom = min(h, int(round(y + fh * 0.925)))
    mask[:top, :] = 0
    mask[bottom:, :] = 0
    mask[:, max(0, min(w, int(firewall_x))):] = 0

    # Also keep the mask local to PERSON-A's detected face envelope.
    left = max(0, int(round(x + fw * 0.055)))
    right = min(w, int(round(x + fw * 0.945)))
    mask[:, :left] = 0
    mask[:, right:] = 0
    return mask


def _source_pixel_transfer_v254(stage1: bytes, source: bytes, model_path) -> bytes:
    """Landmark-fit + target-mask + seamless boundary + source-detail interior."""
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    sh, sw = source_im.shape[:2]

    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    left = target[:, :firewall_x].copy()
    source_bbox, source_pts = v253._yunet_face(source_im, model_path, label="source_photo3")
    target_bbox, target_pts = v253._yunet_face(left, model_path, label="target_person_a")

    matrix, transform_mode, sim_err, fit_err, anisotropy = _choose_transform(source_pts, target_pts)
    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    mean_scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
    if not (0.20 <= mean_scale <= 1.45):
        raise RuntimeError(f"V254 invalid face transform scale={mean_scale:.3f}")

    warped = cv2.warpAffine(
        source_im,
        matrix,
        (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    hard_mask = _target_face_mask(target.shape, target_bbox, firewall_x)
    area = int((hard_mask > 80).sum())
    if area < 4000:
        raise RuntimeError(f"V254 target face mask too small: {area}")

    matched = v253._colour_match_lab(warped, target, hard_mask)

    ys, xs = np.where(hard_mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V254 target face mask empty")
    clone_center = (int(round((int(xs.min()) + int(xs.max())) / 2.0)), int(round((int(ys.min()) + int(ys.max())) / 2.0)))

    clone_mode = "poisson_normal"
    try:
        integrated = cv2.seamlessClone(matched, target, hard_mask, clone_center, cv2.NORMAL_CLONE)
    except Exception as exc:
        # Deterministic non-generative fallback: feather only the same conservative
        # target-space face mask.  V253 itself is still the outer failure fallback.
        clone_mode = "feather_fallback"
        _log("AI_SELFIE_V254_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        sigma = max(6.0, min(20.0, float(min(target_bbox[2], target_bbox[3])) * 0.025))
        soft = cv2.GaussianBlur(hard_mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
        alpha = (soft.astype(np.float32) / 255.0)[:, :, None]
        integrated = np.clip(matched.astype(np.float32) * alpha + target.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)

    # Poisson solves the boundary but can soften the actual source face.  Reinject
    # untouched matched source pixels only well inside the face, far from seams.
    face_min = float(min(target_bbox[2], target_bbox[3]))
    erode_px = max(11, min(55, int(round(face_min * 0.075))))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1, erode_px * 2 + 1))
    inner = cv2.erode(hard_mask, kernel, iterations=1)
    inner_sigma = max(4.0, min(14.0, face_min * 0.018))
    inner = cv2.GaussianBlur(inner, (0, 0), sigmaX=inner_sigma, sigmaY=inner_sigma)
    detail_alpha = (inner.astype(np.float32) / 255.0 * 0.88)[:, :, None]
    final = np.clip(
        matched.astype(np.float32) * detail_alpha
        + integrated.astype(np.float32) * (1.0 - detail_alpha),
        0,
        255,
    ).astype(np.uint8)

    # Belt-and-suspenders PERSON-B firewall: outside the left 55%, preserve the
    # exact Gemini target pixels even if a future OpenCV implementation expands a ROI.
    final[:, firewall_x:] = target[:, firewall_x:]

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V254 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    sx, sy, sfw, sfh = [float(v) for v in source_bbox]
    tx, ty, tfw, tfh = [float(v) for v in target_bbox]
    _log(
        "AI_SELFIE_V254_TRANSFER status=success method=yunet_landmark_fit_target_mask_seamless source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f mask=target_face_no_neck mask_pixels=%s blend=%s detail_reinject=0.88 hero_firewall_x=%s output=png bytes=%s source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh, transform_mode, sim_err, fit_err, anisotropy,
        mean_scale, area, clone_mode, firewall_x, len(output),
    )
    return output


async def _true_face_transfer_v254(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V254 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v254(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_landmark_fit_seamless_source_v254"
        return final, "opencv_yunet_landmark_fit_seamless_real_source_pixels"
    except Exception as exc:
        _log("AI_SELFIE_V254_TRANSFER status=fallback_v253 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        if not callable(_BASE_TRUE_FACE_TRANSFER):
            raise
        return await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V253, then own only prompt-fit and PERSON-A compositor."""
    global _BASE_V253_ENFORCE
    if not callable(_BASE_V253_ENFORCE):
        raise RuntimeError("V254 base V253 enforcer was not captured")

    _BASE_V253_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._stage1_prompt = _stage1_prompt_v254
    transfer._true_face_transfer = _true_face_transfer_v254
    # Delivery remains the proven V253 original-document implementation.
    delivery._deliver = v253._deliver_original

    # Any historical late enforcer must return to V254, while the V251 callback
    # remains the single Telegram generation owner.
    v253.enforce_runtime = enforce_runtime
    v252.enforce_runtime = enforce_runtime
    v251.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, delivery, v241, v245, v246, v247, v249, v250, v251, v252, v253):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v254-front-camera-yunet-landmark-fit-seamless-source-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression + V254 geometry-fit scaffold -> YuNet 5-landmark bounded transform -> "
            "target-space no-neck face mask -> LAB match + Poisson boundary -> real source-detail interior -> "
            "native PNG -> V253 original Telegram document; V253 fallback only"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V254_ENFORCE status=ok base=v253 stage1_geometry_fit=true landmarks=5 transform=similarity_or_bounded_affine mask=target_space_no_neck blend=poisson_plus_source_interior source_pixels=true faceswap_primary=false fallback=v253 delivery=v253_original_document hero=pixel_locked version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V253_ENFORCE, _BASE_TRUE_FACE_TRANSFER, _BASE_STAGE1_PROMPT
    v241, _, _, _, _, _, _, _, transfer, _, _, _ = _modules()

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v253.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V253_ENFORCE = current

    # Freeze the complete proven V253 path as the immediate visual/transport fallback.
    current(bind_generate=True)
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer
    _BASE_STAGE1_PROMPT = transfer._stage1_prompt

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V254 landmark-fit seamless real-source compositor installed over V253", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_choose_transform",
    "_target_face_mask",
    "_source_pixel_transfer_v254",
]
