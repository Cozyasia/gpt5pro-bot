"""Offline L: pointwise mesh correspondence with exact source ray-depth queries.

No source raster triangle-ID matching: tiny triangles remain queryable. This
establishes mesh visibility only, not image segmentation, identity accuracy,
accessory ownership, texture compatibility, or a qualified compositor.
"""

import numpy as np
from .v265_canonical_lab import finite
from .v265_canonical_visibility import rasterize


class SourceRays:
    """Uniform broad-phase bins; bounded pair batches for exact triangle queries."""

    def __init__(self, vertices, triangles, *, bins=16, max_links=1000000):
        self.vertices = finite(vertices).astype(float)
        self.triangles = np.asarray(triangles)
        if (
            self.vertices.ndim != 2
            or self.vertices.shape[1] != 3
            or self.triangles.ndim != 2
            or self.triangles.shape[1] != 3
            or not np.issubdtype(self.triangles.dtype, np.integer)
            or not len(self.triangles)
            or self.triangles.min() < 0
            or self.triangles.max() >= len(self.vertices)
        ):
            raise ValueError("invalid ray topology")
        if not isinstance(bins, int) or not 1 <= bins <= 64:
            raise ValueError("invalid ray bins")
        self.bins = bins
        self.origin = self.vertices[:, :2].min(0)
        self.span = np.maximum(self.vertices[:, :2].max(0) - self.origin, 1e-9)
        self.faces = self.vertices[self.triangles]
        lo = self._cell(self.faces[:, :, :2].min(1))
        hi = self._cell(self.faces[:, :, :2].max(1))
        links = int(np.prod(hi - lo + 1, axis=1).sum())
        if links > max_links:
            raise ValueError("ray index resource bound exceeded")
        self.index = [[] for _ in range(bins * bins)]
        for i in range(len(self.faces)):
            for y in range(lo[i, 1], hi[i, 1] + 1):
                for x in range(lo[i, 0], hi[i, 0] + 1):
                    self.index[y * bins + x].append(i)
        self.index = [np.asarray(ids, dtype=np.int32) for ids in self.index]
        self.links = links

    def _cell(self, xy):
        return np.clip(
            np.floor((xy - self.origin) / self.span * self.bins).astype(int),
            0,
            self.bins - 1,
        )

    def front_depth(self, xy):
        q = finite(xy).astype(float)
        if q.ndim != 2 or q.shape[1] != 2:
            raise ValueError("expected query points Nx2")
        out = np.full(len(q), -np.inf)
        cells = self._cell(q)
        keys = cells[:, 1] * self.bins + cells[:, 0]
        max_pairs = 0
        for key in np.unique(keys):
            points = np.flatnonzero(keys == key)
            faces = self.index[key]
            for begin in range(0, len(points), 128):
                ids = points[begin : begin + 128]
                for start in range(0, len(faces), 512):
                    tri = self.faces[faces[start : start + 512]]
                    if not len(tri):
                        continue
                    p = tri[:, 0, :2]
                    e1 = tri[:, 1, :2] - p
                    e2 = tri[:, 2, :2] - p
                    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
                    measurable = np.abs(det) > 1e-12
                    safe = np.where(measurable, det, 1)
                    delta = q[ids, None, :] - p[None]
                    u = (delta[:, :, 0] * e2[:, 1] - delta[:, :, 1] * e2[:, 0]) / safe
                    v = (delta[:, :, 1] * e1[:, 0] - delta[:, :, 0] * e1[:, 1]) / safe
                    inside = (
                        measurable & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
                    )
                    depth = (
                        tri[:, 0, 2]
                        + u * (tri[:, 1, 2] - tri[:, 0, 2])
                        + v * (tri[:, 2, 2] - tri[:, 0, 2])
                    )
                    out[ids] = np.maximum(
                        out[ids], np.where(inside, depth, -np.inf).max(1)
                    )
                    max_pairs = max(max_pairs, len(ids) * len(tri))
        return out, max_pairs


def correspondence(source, final, triangles, target_roi, *, max_side=256):
    """Return source coordinates and conservative visibility for target samples.

    Larger camera-space z is nearer. Correspondence is affine within each
    triangle, matching L's current affine camera, not a perspective renderer.
    """
    source, final = finite(source), finite(final)
    if source.shape != final.shape:
        raise ValueError("incompatible correspondence topology")
    target = rasterize(final, triangles, target_roi, max_side=max_side)
    owner = target["owner"]
    yy, xx = np.nonzero(owner >= 0)
    topology = np.asarray(triangles)
    rays = SourceRays(source, triangles)
    tolerance = (
        32 * np.finfo(np.float32).eps * max(1.0, float(np.abs(source[:, 2]).max()))
    )
    mapping = np.full((*owner.shape, 2), np.nan, np.float32)
    mask = np.zeros(owner.shape, bool)
    count = 0
    max_pairs = 0
    # Full native ROI never allocates all sample x vertex x coordinate tensors.
    for start in range(0, len(xx), 4096):
        x, y = xx[start : start + 4096], yy[start : start + 4096]
        tri = topology[owner[y, x]]
        pixel = (
            np.column_stack((x + 0.5, y + 0.5)) / target["scale"] + target["roi"][:2]
        )
        p = final[tri].astype(float)
        e1, e2 = p[:, 1, :2] - p[:, 0, :2], p[:, 2, :2] - p[:, 0, :2]
        delta = pixel - p[:, 0, :2]
        det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        u = (delta[:, 0] * e2[:, 1] - delta[:, 1] * e2[:, 0]) / det
        v = (delta[:, 1] * e1[:, 0] - delta[:, 0] * e1[:, 1]) / det
        weights = np.column_stack((1 - u - v, u, v))
        points = np.einsum("nk,nkc->nc", weights, source[tri])
        depth, pairs = rays.front_depth(points[:, :2])
        visible = np.isfinite(depth) & (np.abs(depth - points[:, 2]) <= tolerance)
        mapping[y, x] = points[:, :2]
        mask[y, x] = visible
        count += int(visible.sum())
        max_pairs = max(max_pairs, pairs)
    return {
        "source_xy": mapping,
        "mesh_visible": mask,
        "sample_count": len(xx),
        "mesh_visible_samples": count,
        "mesh_occluded_or_unknown_samples": len(xx) - count,
        "max_query_triangle_pairs": max_pairs,
        "index_links": rays.links,
        "numeric_depth_tolerance": tolerance,
        "max_side": max_side,
        "image_semantics_verified": False,
        "render_prequalified": False,
    }
