"""Offline V265 ablations. Never installed by production bootstrap.

All modes reuse V265 correspondence, ocular selector, original PNG encoder and
same-engine strict path. Pose adaptation is the existing similarity+dense field;
this module does not claim a validated 3D identity/pose disentanglement.
"""

from __future__ import annotations
from contextlib import contextmanager
import cv2
import numpy as np
from neyrobot_prod import dense68_engine_v265 as engine

MODES = ("A_baseline", "B_mask", "C_core", "D_mask_core", "E_mask_frequency")


def full_face_support(shape, dense, firewall_x):
    """Roll-equivariant jaw-to-conservative-forehead support, no dilation below jaw.

    68-point models do not locate the hairline. The top cap uses half the local
    eye-to-brow distance above the brows, rather than claiming hair segmentation.
    Jaw points are boundary members (positive alpha); pixels outside the polygon
    have EXACT zero support. True hairline/occlusion semantics require extra data.
    """
    p = np.asarray(dense, np.float32)
    if p.shape != (68, 2) or not np.isfinite(p).all():
        raise ValueError("invalid dense face")
    eyes = np.array([p[36:42].mean(0), p[42:48].mean(0)])
    xaxis = eyes[1] - eyes[0]
    iod = float(np.linalg.norm(xaxis))
    if iod < 8:
        raise ValueError("insufficient eye baseline")
    xaxis /= iod
    down = np.array([-xaxis[1], xaxis[0]])
    if np.dot(p[8] - eyes.mean(0), down) < 0:
        down = -down
    brows = p[17:27].copy()
    heights = np.maximum(
        0,
        np.array(
            [np.dot(eyes[0] - q, down) for q in brows[:5]]
            + [np.dot(eyes[1] - q, down) for q in brows[5:]]
        ),
    )
    # Conservative forehead cap, in face coordinates; no image-y chin cutoff.
    forehead = brows - down[None, :] * np.minimum(heights * 0.5, iod * 0.18)[:, None]
    ring = np.concatenate([p[:17], forehead])
    hull = cv2.convexHull(np.round(ring).astype(np.int32))
    mask = np.zeros(shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    mask[:, max(0, min(mask.shape[1], int(firewall_x))) :] = 0
    return mask


def interior_alpha(mask, face_min):
    binary = (mask > 80).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    width = float(np.clip(face_min * 0.025, 8, 24))
    # Positive jaw-boundary ownership with inward-only feather: no neck spill.
    alpha = engine._smoothstep01((distance + 1) / width) * binary
    return alpha


def frequency_core(source, target, mask, face_min):
    """Source spatial core, only very broad target illumination residual.

    Sigma tracks face size, never eye/nose feature width. This is an ablation,
    not a relighting model; cast-shadow and specular changes remain unsupported.
    Every float buffer is face-ROI-sized, and the residual is single-channel.
    """
    matched = engine._colour_match_lab_roi_only(source, target, mask)
    s = cv2.cvtColor(matched, cv2.COLOR_BGR2LAB)
    t = cv2.cvtColor(target, cv2.COLOR_BGR2LAB)
    residual = t[:, :, 0].astype(np.float32) - s[:, :, 0].astype(np.float32)
    del t
    illumination = cv2.GaussianBlur(residual, (0, 0), sigmaX=max(12, face_min * 0.22))
    s[:, :, 0] = np.clip(s[:, :, 0].astype(np.float32) + illumination, 0, 255).astype(
        np.uint8
    )
    del residual, illumination
    adapted = cv2.cvtColor(s, cv2.COLOR_LAB2BGR)
    del s
    alpha = interior_alpha(mask, face_min)
    out = target.copy()
    # Channel-at-a-time blend avoids two HxWx3 float arrays.
    for c in range(3):
        out[:, :, c] = np.clip(
            adapted[:, :, c].astype(np.float32) * alpha
            + target[:, :, c].astype(np.float32) * (1 - alpha),
            0,
            255,
        ).astype(np.uint8)
    out[mask <= 80] = target[mask <= 80]
    return out


@contextmanager
def variant(mode, source_dense, target_dense, projected_dense, face_min):
    if mode not in MODES:
        raise ValueError("unknown ablation")
    original_compose = engine._structure_first_compose_roi
    original_mask = engine._landmark_anatomy_mask

    # Target semantic boundary is used as support. desired landmarks own source
    # warp, not the support silhouette; never extrapolate source pixels into neck.
    def mask(shape, bbox, points, firewall):
        return full_face_support(shape, target_dense, firewall)

    def compose(corrected, target, support, minimum, *, strict):
        if mode == "E_mask_frequency":
            out = frequency_core(corrected, target, support, minimum)
        else:
            out = planar_core(corrected, target, support, minimum)
        return out, "offline_" + mode, 0, 0, 0

    try:
        if mode in ("B_mask", "D_mask_core", "E_mask_frequency"):
            engine._landmark_anatomy_mask = mask
        if mode in ("C_core", "D_mask_core", "E_mask_frequency"):
            engine._structure_first_compose_roi = compose
        yield
    finally:
        engine._structure_first_compose_roi = original_compose
        engine._landmark_anatomy_mask = original_mask


def planar_core(source, target, mask, face_min):
    """Planar relighting without the older full N-by-3 float64 design matrix."""
    matched = engine._colour_match_lab_roi_only(source, target, mask)
    s = cv2.cvtColor(matched, cv2.COLOR_BGR2LAB)
    del matched
    t = cv2.cvtColor(target, cv2.COLOR_BGR2LAB)
    residual = t[:, :, 0].astype(np.float32) - s[:, :, 0].astype(np.float32)
    del t
    h, w = mask.shape
    x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
    m = (mask > 80).astype(np.float32)
    sums = lambda z: float(np.sum(z, dtype=np.float64))
    normal = np.array(
        [
            [sums(m), sums(m * x), sums(m * y)],
            [sums(m * x), sums(m * x * x), sums(m * x * y)],
            [sums(m * y), sums(m * x * y), sums(m * y * y)],
        ]
    )
    rhs = np.array([sums(residual * m), sums(residual * m * x), sums(residual * m * y)])
    c = np.linalg.solve(normal, rhs)
    illumination = c[0] + c[1] * x + c[2] * y
    s[:, :, 0] = np.clip(s[:, :, 0].astype(np.float32) + illumination, 0, 255).astype(
        np.uint8
    )
    del residual, m, illumination
    adapted = cv2.cvtColor(s, cv2.COLOR_LAB2BGR)
    del s
    alpha = interior_alpha(mask, face_min)
    out = target.copy()
    for channel in range(3):
        out[:, :, channel] = np.clip(
            adapted[:, :, channel].astype(np.float32) * alpha
            + target[:, :, channel].astype(np.float32) * (1 - alpha),
            0,
            255,
        ).astype(np.uint8)
    out[mask <= 80] = target[mask <= 80]
    return out
