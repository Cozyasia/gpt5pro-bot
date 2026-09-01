# -*- coding: utf-8 -*-
"""V264 ocular source lock.

PIPNet-68 constrains eyelid/brow geometry but does not contain iris/pupil landmarks.
Poisson/LAB compositing can therefore preserve a synthetic target gaze even when all
68 contour metrics pass. This overlay keeps the accepted 68-point geometry exactly
as-is and restores only the source eye texture *after the same dense geometry*.

There is no second eye warp model, no third candidate, and no new Telegram route.
Each eye is similarity-fitted from the source 68-point eye contour to the already
produced final eye contour, colour-matched in luminance only, then feathered inside a
small ocular mask. The candidate is re-scored with the normal MobileFace + dense gate
before production selection. PERSON-B and the rest of PERSON-A remain byte-identical.
"""
from __future__ import annotations

from typing import Any, Callable

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v264_dense68_roi_production as v264

VERSION = v264.VERSION
_INSTALLED = False
_BASE_ATTEMPT: Callable[..., Any] | None = None

# Enough to preserve iris/pupil/eyelash signal without producing a pasted eye edge.
_OCULAR_ALPHA = 0.92
_OCULAR_MARGIN_FRACTION = 0.20
_OCULAR_FEATHER_FRACTION = 0.075
_OCULAR_MIN_MARGIN = 4
_OCULAR_MAX_MARGIN = 16
_OCULAR_MIN_FEATHER = 1.5
_OCULAR_MAX_FEATHER = 5.0


def _log(message: str, *args: Any) -> None:
    v264._log(message, *args)


def _match_eye_luminance(source_roi, target_roi, mask):
    """Match only LAB-L so source iris/chroma identity is not replaced by target."""
    import cv2
    import numpy as np

    region = np.asarray(mask) > 32
    if int(region.sum()) < 24:
        return source_roi.copy()
    src_lab = cv2.cvtColor(source_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt_lab = cv2.cvtColor(target_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    s = src_lab[:, :, 0][region]
    t = tgt_lab[:, :, 0][region]
    sm, tm = float(s.mean()), float(t.mean())
    ss, ts = float(s.std()), float(t.std())
    gain = 1.0 if ss < 1.0 else max(0.82, min(1.18, ts / ss))
    src_lab[:, :, 0] = np.clip((src_lab[:, :, 0] - sm) * gain + tm, 0.0, 255.0)
    return cv2.cvtColor(src_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def _eye_box(points, frame_w: int, frame_h: int) -> tuple[int, int, int, int, float]:
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
        raise RuntimeError("V264 ocular eye box is too small")
    return x0, y0, x1, y1, max(eye_w, eye_h)


def _ocular_mask(points, box, eye_span: float):
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(v) for v in box]
    local = np.asarray(points, dtype=np.float32).reshape(-1, 2).copy()
    local[:, 0] -= float(x0)
    local[:, 1] -= float(y0)
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(local).astype(np.int32), 255, lineType=cv2.LINE_AA)
    dilate = max(1, int(round(float(eye_span) * 0.07)))
    kernel_size = max(3, dilate * 2 + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    mask = cv2.dilate(mask, kernel, iterations=1)
    sigma = max(_OCULAR_MIN_FEATHER, min(_OCULAR_MAX_FEATHER, float(eye_span) * _OCULAR_FEATHER_FRACTION))
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return mask, float(sigma)


def _restore_one_eye(final, source_im, source_eye, final_eye) -> tuple[bool, float, float]:
    """Restore source ocular texture into the already accepted final eye geometry."""
    import cv2
    import numpy as np

    src = np.asarray(source_eye, dtype=np.float32).reshape(-1, 2)
    dst = np.asarray(final_eye, dtype=np.float32).reshape(-1, 2)
    if src.shape[0] < 6 or dst.shape[0] < 6:
        return False, 0.0, 0.0

    matrix, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if matrix is None:
        return False, 0.0, 0.0
    a, b = float(matrix[0, 0]), float(matrix[0, 1])
    scale = max(1.0e-8, (a * a + b * b) ** 0.5)
    if not (0.45 <= scale <= 2.10):
        return False, scale, 0.0

    fh, fw = final.shape[:2]
    x0, y0, x1, y1, eye_span = _eye_box(dst, fw, fh)
    local_matrix = np.asarray(matrix, dtype=np.float32).copy()
    local_matrix[0, 2] -= float(x0)
    local_matrix[1, 2] -= float(y0)
    warped = cv2.warpAffine(
        source_im,
        local_matrix,
        (x1 - x0, y1 - y0),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    mask, sigma = _ocular_mask(dst, (x0, y0, x1, y1), eye_span)
    target_roi = final[y0:y1, x0:x1]
    matched = _match_eye_luminance(warped, target_roi, mask)

    alpha = (mask.astype(np.float32) / 255.0)[:, :, None] * float(_OCULAR_ALPHA)
    mixed = np.clip(
        matched.astype(np.float32) * alpha + target_roi.astype(np.float32) * (1.0 - alpha),
        0.0,
        255.0,
    ).astype(np.uint8)
    final[y0:y1, x0:x1] = mixed
    return True, float(scale), float(sigma)


def _recompute_metrics(output: bytes, source: bytes, desired_dense, yunet_path, dense_path, recognition_path, base_metrics):
    import numpy as np

    final = v253._decode_bgr(output)
    source_im = v253._decode_bgr(source)
    fh, fw = final.shape[:2]
    firewall_x = max(256, min(fw, int(round(fw * 0.55))))
    source_bbox, _ = v253._yunet_face(source_im, yunet_path, label="source_photo3_v264_ocular_eval")
    final_bbox, _ = v253._yunet_face(final[:, :firewall_x], yunet_path, label="final_person_a_v264_ocular_eval")
    source_dense = v263._dense_landmarks_68(source_im, source_bbox, dense_path, label="source_photo3_ocular_eval")
    final_dense = v263._dense_landmarks_68(final, final_bbox, dense_path, label="final_person_a_ocular_eval")
    source_embedding = v263._mobileface_embedding(source_im, source_dense, recognition_path)
    final_embedding = v263._mobileface_embedding(final, final_dense, recognition_path)
    metrics = dict(v263._quality_metrics(source_embedding, final_embedding, desired_dense, final_dense))
    for key in (
        "source_face_short", "target_face_short", "similarity_rms_normalized",
        "max_dense_shift_normalized",
    ):
        if key in base_metrics:
            metrics[key] = float(base_metrics[key])
    return metrics, source_im, source_dense, final, final_dense


def _encode_png(frame) -> bytes:
    import cv2
    ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V264 ocular source lock PNG encode failed")
    return bytes(encoded.tobytes())


def _apply_ocular_lock(output: bytes, source: bytes, desired_dense, yunet_path, dense_path, recognition_path, base_metrics):
    """Use the same accepted dense geometry, but make actual eye texture source-owned."""
    try:
        metrics_before, source_im, source_dense, final, final_dense = _recompute_metrics(
            output, source, desired_dense, yunet_path, dense_path, recognition_path, base_metrics
        )
        applied = 0
        scales: list[float] = []
        sigmas: list[float] = []
        for eye_ids in (v263._RIGHT_EYE, v263._LEFT_EYE):
            ok, scale, sigma = _restore_one_eye(
                final,
                source_im,
                source_dense[list(eye_ids)],
                final_dense[list(eye_ids)],
            )
            if ok:
                applied += 1
                scales.append(scale)
                sigmas.append(sigma)
        if applied != 2:
            _log(
                "AI_SELFIE_V264_OCULAR_LOCK status=skipped reason=eye_restore_incomplete applied=%s/2",
                applied,
            )
            return output, base_metrics

        encoded = _encode_png(final)
        metrics_after, _, _, _, _ = _recompute_metrics(
            encoded, source, desired_dense, yunet_path, dense_path, recognition_path, base_metrics
        )
        _log(
            "AI_SELFIE_V264_OCULAR_LOCK status=applied method=source_texture_on_existing_dense68_geometry "
            "eyes=2 independent_geometry_warp=false iris_pupil_source_owned=true alpha=%.2f "
            "eye_scales=%s feather_sigma=%s identity_before=%.4f identity_after=%.4f "
            "eye_asym_before=%.4f eye_asym_after=%.4f bytes=%s",
            _OCULAR_ALPHA,
            ",".join(f"{v:.3f}" for v in scales),
            ",".join(f"{v:.2f}" for v in sigmas),
            float(metrics_before.get("identity_similarity_cosine", 0.0)),
            float(metrics_after.get("identity_similarity_cosine", 0.0)),
            float(metrics_before.get("eye_asymmetry_delta", 0.0)),
            float(metrics_after.get("eye_asymmetry_delta", 0.0)),
            len(encoded),
        )
        return encoded, metrics_after
    except Exception as exc:
        # Ocular preservation is a refinement only. Never turn a previously valid
        # production candidate into a hard failure because this local texture lock
        # could not be applied on an unusual pose.
        _log(
            "AI_SELFIE_V264_OCULAR_LOCK status=fallback_original reason=%s:%s",
            type(exc).__name__, str(exc)[:260],
        )
        return output, base_metrics


def _transfer_attempt_ocular_locked(stage1, source, yunet_path, dense_path, recognition_path, *, strict: bool):
    if _BASE_ATTEMPT is None:
        raise RuntimeError("V264 ocular source lock base attempt is unavailable")
    output, metrics, desired_dense = _BASE_ATTEMPT(
        stage1, source, yunet_path, dense_path, recognition_path, strict=strict
    )
    # Dense V264 already guarantees safe source sampling before we get here. Provider
    # rescue remains the owner for overscale/small-source preflight failures.
    locked_output, locked_metrics = _apply_ocular_lock(
        bytes(output or b""), bytes(source or b""), desired_dense,
        yunet_path, dense_path, recognition_path, metrics,
    )
    return locked_output, locked_metrics, desired_dense


def install() -> None:
    global _INSTALLED, _BASE_ATTEMPT
    current = v264._transfer_attempt_roi
    if current is _transfer_attempt_ocular_locked:
        _INSTALLED = True
        return
    if not _INSTALLED:
        _BASE_ATTEMPT = current
    elif not callable(_BASE_ATTEMPT):
        raise RuntimeError("V264 ocular source lock lost base attempt")

    v264._transfer_attempt_roi = _transfer_attempt_ocular_locked
    _INSTALLED = True
    _log(
        "AI_SELFIE_V264_OCULAR_LOCK_INSTALL status=ok geometry=dense68_unchanged "
        "iris_pupil=source_texture_locked max_attempts=2 no_new_model=true roi_eye_only=true "
        "person_b=pixel_locked"
    )


__all__ = [
    "VERSION", "install", "_apply_ocular_lock", "_restore_one_eye",
    "_match_eye_luminance", "_transfer_attempt_ocular_locked",
]
