"""Offline texture sampling for L; no scene compositor or semantic inference.

source_xy uses pixel-boundary coordinates: source pixel [y,x] is centred at
(x+.5,y+.5), matching the correspondence rasterizer. All contributors to bilinear
sampling must be inside the image and source-owned. Unknown pixels stay absent.
"""

import numpy as np


def sample_owned_texture(image, source_xy, mesh_visible, source_owned, target_owned):
    image = np.asarray(image)
    xy = np.asarray(source_xy)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("expected uint8 RGB/BGR source")
    if xy.ndim != 3 or xy.shape[2] != 2:
        raise ValueError("expected ROI source coordinate map")
    masks = [np.asarray(x) for x in (mesh_visible, source_owned, target_owned)]
    if (
        any(x.dtype != np.bool_ for x in masks)
        or masks[0].shape != xy.shape[:2]
        or masks[1].shape != image.shape[:2]
        or masks[2].shape != xy.shape[:2]
    ):
        raise ValueError("explicit boolean ownership masks required")
    visible, source_mask, target_mask = masks
    output = np.zeros((*xy.shape[:2], 3), dtype=np.uint8)
    available = np.zeros(xy.shape[:2], dtype=bool)
    yy, xx = np.nonzero(visible & target_mask & np.isfinite(xy).all(axis=2))
    h, w = image.shape[:2]
    for start in range(0, len(xx), 4096):
        y, x = yy[start : start + 4096], xx[start : start + 4096]
        p = xy[y, x].astype(float) - 0.5
        # Validate before integer conversion; no overflow/clamping of bad maps.
        valid = (
            (p[:, 0] >= 0) & (p[:, 0] <= w - 1) & (p[:, 1] >= 0) & (p[:, 1] <= h - 1)
        )
        y, x, p = y[valid], x[valid], p[valid]
        if not len(p):
            continue
        lo = np.floor(p).astype(int)
        hi = np.minimum(lo + 1, [w - 1, h - 1])
        dx, dy = (p - lo).T
        coords = [
            (lo[:, 1], lo[:, 0]),
            (lo[:, 1], hi[:, 0]),
            (hi[:, 1], lo[:, 0]),
            (hi[:, 1], hi[:, 0]),
        ]
        weights = [(1 - dx) * (1 - dy), dx * (1 - dy), (1 - dx) * dy, dx * dy]
        allowed = np.ones(len(p), bool)
        colour = np.zeros((len(p), 3), float)
        for (sy, sx), weight in zip(coords, weights):
            allowed &= (weight == 0) | source_mask[sy, sx]
            colour += image[sy, sx] * weight[:, None]
        output[y[allowed], x[allowed]] = (
            np.rint(colour[allowed]).clip(0, 255).astype(np.uint8)
        )
        available[y[allowed], x[allowed]] = True
    return {
        "texture": output,
        "available": available,
        "available_samples": int(available.sum()),
        "blocked_samples": int((visible & ~available).sum()),
        "semantic_masks_are_caller_evidence_not_inferred": True,
        "render_prequalified": False,
    }


def pixel_centres_to_mesh_boundaries(vertices):
    """Convert OpenCV centre coordinates to the rasterizer's boundary convention.

    Apply to BOTH projected source and final meshes before correspondence.
    Camera depth and image pixel values are unchanged.
    """
    points = np.asarray(vertices, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("expected finite projected mesh")
    out = points.copy()
    out[:, :2] += 0.5
    return out
