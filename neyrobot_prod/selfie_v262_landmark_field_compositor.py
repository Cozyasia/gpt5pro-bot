# -*- coding: utf-8 -*-
"""V262: unified 5-landmark face deformation with no oval source core.

V261 production proved that hiding the edge of the historical V255 ellipse is not
sufficient: the ellipse itself remains the geometry of the transferred low-frequency
face, while V260 can independently move an eye after the rest of the face has already
been composited.  That can produce a pasted oval, an overlaid eye and a mouth that no
longer agrees with the corrected eye geometry.

V262 replaces the final PERSON-A transfer path rather than adding another patch:
- Gemini stage-1 remains the complete scene and PERSON-B owner;
- YuNet still supplies the same five source/target landmarks;
- one global bounded similarity/affine fit establishes pose and scale;
- one compact all-five-landmark deformation field corrects both eyes, nose and both
  mouth corners together before any final compositing;
- the final transfer mask is an anatomical landmark hull, not a bbox/source ellipse;
- Poisson integration transfers source facial gradients without a solid low-frequency
  source-pixel core;
- only source high-frequency detail is reintroduced away from the boundary;
- there is no independent eye overlay and no raw low-frequency face reinjection;
- PERSON-B is restored byte-for-byte and V253 original-document delivery is retained;
- all float32 deformation/detail work stays inside a compact PERSON-A ROI;
- V258 is retained only as a conservative failure fallback.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v258_inner_face_integration as v258
from neyrobot_prod import selfie_v259_eye_landmark_protection as v259
from neyrobot_prod import selfie_v260_eye_roi_memory_safe as v260
from neyrobot_prod import selfie_v261_edge_harmonization as v261

VERSION = "v262-landmark-field-compositor-2026-08-27"
_INSTALLED = False
_BASE_V261_ENFORCE = None

_MAX_LANDMARK_RESIDUAL = 28.0
_FIELD_SIGMA_X_FRACTION = 0.075
_FIELD_SIGMA_Y_FRACTION = 0.065
_FIELD_SIGMA_MIN = 28.0
_FIELD_SIGMA_MAX = 72.0
_DETAIL_SIGMA = 1.8
_DETAIL_STRENGTH = 0.78
_DETAIL_BOUNDARY_FRACTION = 0.040
_DETAIL_BOUNDARY_MIN = 14.0
_DETAIL_BOUNDARY_MAX = 34.0


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


def _smoothstep01(values):
    import numpy as np

    t = np.clip(values, 0.0, 1.0).astype(np.float32, copy=False)
    return t * t * (3.0 - 2.0 * t)


def _landmark_anatomy_mask(shape, bbox, landmarks, firewall_x: int):
    """Build an inner-face polygon from real landmarks; intentionally no ellipse."""
    import cv2
    import numpy as np

    h, w = int(shape[0]), int(shape[1])
    x, y, fw, fh = [float(v) for v in bbox]
    pts = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)

    # YuNet order is eye, eye, nose, mouth-corner, mouth-corner.  Sorting each pair
    # by x makes the polygon independent of camera mirroring.
    eyes = pts[0:2][np.argsort(pts[0:2, 0])]
    mouths = pts[3:5][np.argsort(pts[3:5, 0])]
    left_eye, right_eye = eyes[0], eyes[1]
    nose = pts[2]
    left_mouth, right_mouth = mouths[0], mouths[1]

    eye_mid = (left_eye + right_eye) * 0.5
    mouth_mid = (left_mouth + right_mouth) * 0.5

    # The hull intentionally stops inside the jaw/temple/hairline.  Those broad
    # low-frequency regions stay owned by stage-1, which removes the visible face
    # sticker while the real source features still own the identity gradients.
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

    # A tiny close only removes polygon raster notches; it does not create a new
    # oval and does not expand into jaw/neck/hair.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def _mask_box(mask, *, pad: int, firewall_x: int):
    import numpy as np

    h, _ = mask.shape[:2]
    ys, xs = np.where(mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V262 anatomical landmark mask empty")
    x0 = max(0, int(xs.min()) - int(pad))
    y0 = max(0, int(ys.min()) - int(pad))
    x1 = min(int(firewall_x), int(xs.max()) + int(pad) + 1)
    y1 = min(int(h), int(ys.max()) + int(pad) + 1)
    if x1 - x0 < 120 or y1 - y0 < 140:
        raise RuntimeError(f"V262 anatomical ROI too small: {x1-x0}x{y1-y0}")
    return x0, y0, x1, y1


def _deform_all_landmarks_roi(warped, target_pts, residuals, box, face_min: float):
    """Apply one smooth all-five-landmark inverse field inside a compact ROI."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    roi_w, roi_h = int(x1 - x0), int(y1 - y0)
    sigma_x = max(_FIELD_SIGMA_MIN, min(_FIELD_SIGMA_MAX, float(face_min) * _FIELD_SIGMA_X_FRACTION))
    sigma_y = max(_FIELD_SIGMA_MIN, min(_FIELD_SIGMA_MAX, float(face_min) * _FIELD_SIGMA_Y_FRACTION))

    gx = np.arange(x0, x1, dtype=np.float32)[None, :]
    gy = np.arange(y0, y1, dtype=np.float32)[:, None]
    sum_w = np.zeros((roi_h, roi_w), dtype=np.float32)
    sum_dx = np.zeros((roi_h, roi_w), dtype=np.float32)
    sum_dy = np.zeros((roi_h, roi_w), dtype=np.float32)

    target_pts = np.asarray(target_pts, dtype=np.float32).reshape(5, 2)
    residuals = np.asarray(residuals, dtype=np.float32).reshape(5, 2)
    for i in range(5):
        cx, cy = float(target_pts[i, 0]), float(target_pts[i, 1])
        wx = (gx - cx) / max(1.0, sigma_x)
        wy = (gy - cy) / max(1.0, sigma_y)
        weight = np.exp(-0.5 * (wx * wx + wy * wy)).astype(np.float32, copy=False)
        sum_w += weight
        sum_dx += weight * float(residuals[i, 0])
        sum_dy += weight * float(residuals[i, 1])

    inv_w = 1.0 / np.maximum(sum_w, 1.0e-6)
    support = np.clip(sum_w, 0.0, 1.0)
    disp_x = sum_dx * inv_w * support
    disp_y = sum_dy * inv_w * support

    # residual = target - globally-projected source.  For inverse remap, output at
    # target coordinate samples from coordinate target-residual.
    map_x = np.broadcast_to(gx, (roi_h, roi_w)).copy() - disp_x
    map_y = np.broadcast_to(gy, (roi_h, roi_w)).copy() - disp_y
    corrected_roi = cv2.remap(
        warped,
        map_x,
        map_y,
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return corrected_roi, sigma_x, sigma_y


def _source_pixel_transfer_v262(stage1: bytes, source: bytes, model_path) -> bytes:
    """Unified 5-landmark deformation -> anatomical Poisson -> source detail only."""
    import cv2
    import numpy as np

    target = v253._decode_bgr(stage1)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    sh, sw = source_im.shape[:2]
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))

    source_bbox, source_pts = v253._yunet_face(source_im, model_path, label="source_photo3_v262")
    target_bbox, target_pts = v253._yunet_face(
        target[:, :firewall_x], model_path, label="target_person_a_v262"
    )
    matrix, transform_mode, sim_err, fit_err, anisotropy = v254._choose_transform(source_pts, target_pts)

    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    mean_scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = float(min(sfw, sfh))
    face_min = float(min(tfw, tfh))
    if not (0.20 <= mean_scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V262 invalid face transform scale={mean_scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(f"V262 source sampling too small: native_short={native_face_short:.1f}")

    projected_pts = _project_points(matrix, source_pts)
    residuals = np.asarray(target_pts, dtype=np.float32) - np.asarray(projected_pts, dtype=np.float32)
    residual_norms = np.linalg.norm(residuals, axis=1)
    max_residual = float(residual_norms.max())
    if max_residual > _MAX_LANDMARK_RESIDUAL:
        raise RuntimeError(f"V262 landmark residual too large: max={max_residual:.2f}px")

    # One global source warp only.  All local geometry correction happens together
    # in the compact PERSON-A ROI below; there are no later eye/mouth patch warps.
    warped = cv2.warpAffine(
        source_im,
        matrix,
        (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    anatomy_mask = _landmark_anatomy_mask(target.shape, target_bbox, target_pts, firewall_x)
    mask_pixels = int((anatomy_mask > 80).sum())
    if mask_pixels < 12000:
        raise RuntimeError(f"V262 anatomical landmark mask too small: pixels={mask_pixels}")

    pad = int(round(max(28.0, min(72.0, face_min * 0.085))))
    box = _mask_box(anatomy_mask, pad=pad, firewall_x=firewall_x)
    x0, y0, x1, y1 = box
    corrected_roi, field_sigma_x, field_sigma_y = _deform_all_landmarks_roi(
        warped, target_pts, residuals, box, face_min
    )
    corrected = warped.copy()
    corrected[y0:y1, x0:x1] = corrected_roi

    matched = v253._colour_match_lab(corrected, target, anatomy_mask)
    ys, xs = np.where(anatomy_mask > 80)
    clone_center = (
        int(round((int(xs.min()) + int(xs.max())) / 2.0)),
        int(round((int(ys.min()) + int(ys.max())) / 2.0)),
    )

    blend_mode = "poisson_normal_anatomical_hull"
    try:
        # Poisson owns low-frequency boundary integration.  Unlike V258/V261 there
        # is deliberately no later broad matched-source core blended over it.
        integrated = cv2.seamlessClone(matched, target, anatomy_mask, clone_center, cv2.NORMAL_CLONE)
    except Exception as exc:
        blend_mode = "target_plus_source_detail_fallback"
        _log("AI_SELFIE_V262_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        integrated = target.copy()

    mask_roi = anatomy_mask[y0:y1, x0:x1]
    binary = (mask_roi > 80).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    detail_boundary = max(
        _DETAIL_BOUNDARY_MIN,
        min(_DETAIL_BOUNDARY_MAX, face_min * _DETAIL_BOUNDARY_FRACTION),
    )
    detail_alpha = _smoothstep01(distance / max(1.0, detail_boundary)) * _DETAIL_STRENGTH
    detail_alpha *= binary.astype(np.float32)

    matched_roi = matched[y0:y1, x0:x1]
    integrated_roi = integrated[y0:y1, x0:x1]
    source_low = cv2.GaussianBlur(
        matched_roi,
        (0, 0),
        sigmaX=_DETAIL_SIGMA,
        sigmaY=_DETAIL_SIGMA,
    )
    # Signed source high-frequency only: pores, eyelid/lip edges and local texture.
    # No source low-frequency colour/illumination core is reintroduced here.
    detail = matched_roi.astype(np.float32) - source_low.astype(np.float32)
    final_roi = np.clip(
        integrated_roi.astype(np.float32) + detail * detail_alpha[:, :, None],
        0,
        255,
    ).astype(np.uint8)

    final = integrated
    final[y0:y1, x0:x1] = final_roi
    final[:, firewall_x:] = target[:, firewall_x:]

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V262 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())

    residual_text = ",".join(f"{float(v):.2f}" for v in residual_norms.tolist())
    shift_text = ";".join(
        f"{float(r[0]):.2f},{float(r[1]):.2f}" for r in residuals.tolist()
    )
    _log(
        "AI_SELFIE_V262_TRANSFER status=success method=all5_landmark_field_anatomical_poisson_detail "
        "source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "transform=%s similarity_rms=%.2f fit_rms=%.2f anisotropy=%.3f scale=%.3f "
        "native_face_short=%.1f landmark_residuals=%s landmark_shifts=%s max_residual=%.2f "
        "landmark_field=all5 field_sigma=%.1f,%.1f independent_eye_patch=false "
        "mask=landmark_anatomical_hull ellipse_final_mask=false mask_pixels=%s roi=%sx%s "
        "blend=%s source_high_frequency_only=true detail_sigma=%.1f detail_strength=%.2f "
        "detail_boundary=%.1f raw_low_frequency_reinject=false solid_source_core=false "
        "person_b_untouched=true provider_bypassed=true delivery=v253_original_document "
        "output=png bytes=%s source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh,
        transform_mode, sim_err, fit_err, anisotropy, mean_scale, native_face_short,
        residual_text, shift_text, max_residual, field_sigma_x, field_sigma_y,
        mask_pixels, x1 - x0, y1 - y0, blend_mode,
        _DETAIL_SIGMA, _DETAIL_STRENGTH, detail_boundary, len(output),
    )
    return output


async def _true_face_transfer_v262(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V262 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await v253._ensure_yunet_model()
        final = _source_pixel_transfer_v262(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_all5_landmark_field_v262"
        return final, "opencv_yunet_all5_landmark_field_anatomical_real_source_detail"
    except Exception as exc:
        _log("AI_SELFIE_V262_TRANSFER status=fallback_v258 reason=%s:%s", type(exc).__name__, str(exc)[:300])
        return await v258._true_face_transfer_v258(runtime, stage1, source, source_photo_no)


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert historical overlays, then replace them with the unified V262 owner."""
    global _BASE_V261_ENFORCE
    if not callable(_BASE_V261_ENFORCE):
        raise RuntimeError("V262 base V261 enforcer was not captured")

    _BASE_V261_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v262
    delivery._deliver = v253._deliver_original

    # Historical late enforcers may initialise, but the final PERSON-A transfer owner
    # always resolves back here.  No new callback/payment/scene handler is created.
    v261.enforce_runtime = enforce_runtime
    v260.enforce_runtime = enforce_runtime
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
        v253, v254, v255, v256, v257, v258, v259, v260, v261,
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
            "v262-front-camera-all5-landmark-field-anatomical-poisson-source-detail-lossless-document"
        )
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> YuNet global fit -> V262 unified five-landmark compact deformation "
            "field -> anatomical landmark-hull Poisson integration -> source high-frequency detail only -> "
            "V253 original Telegram document; V258 conservative fallback"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V262_ENFORCE status=ok base=gemini_stage1 source=photo3 landmarks=5 "
        "geometry=unified_all5_landmark_field independent_eye_patch=false "
        "mask=landmark_anatomical_hull ellipse_final_mask=false blend=poisson_plus_source_high_frequency "
        "raw_low_frequency_reinject=false solid_source_core=false full_frame_float_blend=false "
        "source_gate=anatomical_inner_face no_neck=true delivery=v253_original_document "
        "hero=pixel_locked version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V261_ENFORCE

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v261.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V261_ENFORCE = current
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V262 unified landmark-field anatomical compositor installed", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_source_pixel_transfer_v262",
    "_true_face_transfer_v262",
    "_landmark_anatomy_mask",
    "_deform_all_landmarks_roi",
]
