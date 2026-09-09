"""Bounded offline visibility rasterizer for canonical L correspondence.

No image compositor, synthetic completion, accessory inference or eye patch.
Coordinates and depth must be in one declared camera; larger z is nearer.
Visibility changes are NOT labelled deformation foldovers.
"""

import numpy as np
from .v265_canonical_lab import finite


def rasterize(vertices, triangles, roi, *, max_side=256):
    vertices = finite(vertices)
    tri = np.asarray(triangles)
    bounds = finite(roi, (4,))
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 3
        or tri.ndim != 2
        or tri.shape[1] != 3
        or not np.issubdtype(tri.dtype, np.integer)
        or not len(tri)
        or tri.min() < 0
        or tri.max() >= len(vertices)
    ):
        raise ValueError("invalid raster topology")
    if not isinstance(max_side, int) or not 2 <= max_side <= 1024:
        raise ValueError("invalid bounded raster size")
    size = bounds[2:] - bounds[:2]
    if np.any(size <= 0):
        raise ValueError("invalid raster ROI")
    scale = max_side / float(size.max())
    width, height = np.maximum(1, np.ceil(size * scale).astype(int))
    xy = (vertices[:, :2] - bounds[:2]) * scale
    depth = np.full((height, width), -np.inf, np.float32)
    owner = np.full((height, width), -1, np.int32)
    # No dense triangle x canvas tensor: each triangle uses its bounded ROI.
    degenerate = 0
    for index, ids in enumerate(tri):
        p = xy[ids]
        x0, y0 = np.maximum(0, np.floor(p.min(axis=0)).astype(int))
        x1, y1 = np.minimum([width, height], np.ceil(p.max(axis=0)).astype(int))
        e1, e2 = p[1] - p[0], p[2] - p[0]
        det = float(e1[0] * e2[1] - e1[1] * e2[0])
        if abs(det) <= 1e-8:
            degenerate += 1
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        xx, yy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        dx, dy = xx - p[0, 0], yy - p[0, 1]
        u = (dx * e2[1] - dy * e2[0]) / det
        v = (dy * e1[0] - dx * e1[1]) / det
        inside = (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
        z = vertices[ids, 2]
        value = z[0] + u * (z[1] - z[0]) + v * (z[2] - z[0])
        dst = depth[y0:y1, x0:x1]
        take = inside & (value > dst)
        dst[take] = value[take]
        owner[y0:y1, x0:x1][take] = index
    visible = np.zeros(len(tri), bool)
    visible[np.unique(owner[owner >= 0])] = True
    return {
        "owner": owner,
        "depth": depth,
        "visible_triangles": visible,
        "degenerate_triangles": degenerate,
        "scale": scale,
        "roi": bounds,
        "array_bytes": owner.nbytes + depth.nbytes + visible.nbytes,
        "resolution_is_diagnostic_not_pixel_safety": True,
    }


def visibility_audit(source, target, final, triangles, source_roi, target_roi):
    s = rasterize(source, triangles, source_roi)
    t = rasterize(target, triangles, target_roi)
    f = rasterize(final, triangles, target_roi)
    sv, tv, fv = (x["visible_triangles"] for x in (s, t, f))
    return {
        "source_visible_triangles": int(sv.sum()),
        "target_visible_triangles": int(tv.sum()),
        "final_visible_triangles": int(fv.sum()),
        "final_visible_without_source_samples": int((fv & ~sv).sum()),
        "target_to_final_visibility_changes": int((tv != fv).sum()),
        "final_degenerate_triangles": f["degenerate_triangles"],
        "retained_raster_bytes": sum(x["array_bytes"] for x in (s, t, f)),
        "visibility_resolution_max_side": 256,
        "accessory_safety_proven": False,
        "full_resolution_correspondence_verified": False,
    }
