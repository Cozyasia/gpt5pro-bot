"""Bounded offline visibility rasterizer for canonical L correspondence.

No image compositor, synthetic completion, accessory inference or eye patch.
Coordinates and depth must be in one declared camera; larger z is nearer.
Visibility changes are NOT labelled deformation foldovers.
"""

import numpy as np
from .v265_canonical_lab import finite


def rasterize(vertices, triangles, roi, *, max_side=256, triangle_mask=None):
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
    if not isinstance(max_side, int) or not 2 <= max_side <= 1536:
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
    projected = xy[tri]
    edge1 = projected[:, 1] - projected[:, 0]
    edge2 = projected[:, 2] - projected[:, 0]
    determinants = edge1[:, 0] * edge2[:, 1] - edge1[:, 1] * edge2[:, 0]
    # Pixel-centre bounds discard subpixel triangles whose boxes contain no
    # samples before allocating any per-triangle grid. Such triangles are
    # unobserved at this resolution, NOT proven hidden surfaces.
    lower = np.maximum(0, np.ceil(projected.min(axis=1) - 0.5000001).astype(int))
    upper = np.minimum(
        [width, height], np.floor(projected.max(axis=1) - 0.4999999).astype(int) + 1
    )
    selected = (
        np.ones(len(tri), dtype=bool)
        if triangle_mask is None
        else np.asarray(triangle_mask)
    )
    if selected.shape != (len(tri),) or selected.dtype != np.bool_:
        raise ValueError("explicit boolean triangle mask required")
    valid = selected & (np.abs(determinants) > 1e-8) & np.all(upper > lower, axis=1)
    degenerate = int(np.count_nonzero(np.abs(determinants) <= 1e-8))
    for index in np.flatnonzero(valid):
        ids = tri[index]
        p = projected[index]
        x0, y0 = lower[index]
        x1, y1 = upper[index]
        e1, e2 = edge1[index], edge2[index]
        det = float(determinants[index])
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


def mesh_render_audit(source, target, final, triangles, target_roi, *, max_side=256):
    """Audit a cull-first triangle path in one target camera.

    Target-person geometry is used only as an orientation reference. Triangles
    whose L projection reverses that orientation are rejected before z-ordering;
    they can never become visible folded pixels. Holes remain explicit and must
    be handled by the completeness contract, never by a legacy warp fallback.
    """
    source, target, final = (finite(x) for x in (source, target, final))
    topology = np.asarray(triangles, dtype=np.int32)
    if source.shape != target.shape or target.shape != final.shape:
        raise ValueError("incompatible render meshes")
    projected = [x[topology, :2] for x in (source, target, final)]
    determinant = []
    for p in projected:
        a, b = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
        determinant.append(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    sd, td, fd = determinant
    measurable = (np.abs(td) > 1e-8) & (np.abs(fd) > 1e-8)
    orientation_ok = measurable & (td * fd > 0)
    target_raster = rasterize(target, topology, target_roi, max_side=max_side)
    rendered = rasterize(
        final, topology, target_roi, max_side=max_side, triangle_mask=orientation_ok
    )
    target_face = target_raster["owner"] >= 0
    covered = rendered["owner"] >= 0
    visible = rendered["visible_triangles"]
    # Local 2D affine scale is evaluated only for triangles admitted to render.
    ids = np.flatnonzero(orientation_ok)
    if len(ids):
        ta = projected[1][ids, 1:] - projected[1][ids, :1]
        fa = projected[2][ids, 1:] - projected[2][ids, :1]
        tm = ta.transpose(0, 2, 1)
        fm = fa.transpose(0, 2, 1)
        singular = np.linalg.svd(fm @ np.linalg.inv(tm), compute_uv=False)
        stretch_max = float(singular.max())
        compression_min = float(singular.min())
    else:
        stretch_max = None
        compression_min = None
    visible_owner = np.unique(rendered["owner"][covered])
    inverted_visible = int(np.count_nonzero(~orientation_ok[visible_owner]))
    return {
        "triangle_count": int(len(topology)),
        "visible_triangles": int(visible.sum()),
        "back_facing_or_orientation_rejected_triangles": int((~orientation_ok).sum()),
        "degenerate_triangles": int((~measurable).sum()),
        "orientation_reversals_before_cull": int((measurable & (td * fd <= 0)).sum()),
        "inverted_visible_triangles": inverted_visible,
        "uncovered_face_pixels": int((target_face & ~covered).sum()),
        "target_face_pixels": int(target_face.sum()),
        "covered_face_pixels": int((target_face & covered).sum()),
        "max_local_stretch": stretch_max,
        "min_local_compression": compression_min,
        "foldover": bool(inverted_visible),
        "render_completed": True,
        "legacy_warp_fallback_used": False,
        "render_prequalified": False,
        "source_projection_orientation_observed": int(np.count_nonzero(np.abs(sd) > 1e-8)),
        "raster_array_bytes": int(target_raster["array_bytes"] + rendered["array_bytes"]),
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
        "unobserved_triangles_may_be_subpixel_not_occluded": True,
    }
