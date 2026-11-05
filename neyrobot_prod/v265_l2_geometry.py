"""Geometry-only L2 bake-off primitives; never imported by production runtime.

The richer candidate is FaceVerse V4.  A source-specific residual lives in
canonical 3D vertex coordinates.  It is fitted after pose removal, projected
onto expression-invariant landmark motions, bounded, and diffused on topology.
It is deliberately not a 2D warp and has no legacy fallback.
"""

from __future__ import annotations

import hashlib
import numpy as np


FV_ID = 156
FV_EXP = 177
FV_TEX = 251


def split_faceverse(coefficients):
    c = np.asarray(coefficients, np.float32).reshape(-1)
    if c.size != 621 or not np.isfinite(c).all():
        raise ValueError("expected finite FaceVerse 621-vector")
    return {
        "identity": c[:FV_ID],
        "expression": c[FV_ID : FV_ID + FV_EXP],
        "texture": c[FV_ID + FV_EXP : FV_ID + FV_EXP + FV_TEX],
        "lighting": c[584:611],
        "angles": c[611:614],
        "translation": c[614:617],
        "eyes": c[617:621],
    }


def rotation_matrix(angles):
    x, y, z = np.asarray(angles, np.float64)
    sx, sy, sz = np.sin([x, y, z])
    cx, cy, cz = np.cos([x, y, z])
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return (rz @ ry @ rx).T.astype(np.float32)


class FaceVerseGeometry:
    def __init__(self, pack):
        with np.load(pack, allow_pickle=False) as z:
            self.mean = z["mean"].astype(np.float32)
            self.identity_basis = z["identity_basis"].astype(np.float32)
            self.expression_basis = z["expression_basis"].astype(np.float32)
            self.triangles = z["triangles"].astype(np.int32)
            self.landmarks = z["landmarks"].astype(np.int32)
            self.face_mask = z["face_mask"].astype(bool)
        if self.identity_basis.shape[2] != FV_ID or self.expression_basis.shape[2] != FV_EXP:
            raise ValueError("unexpected FaceVerse bases")

    @property
    def resident_array_bytes(self):
        return int(sum(x.nbytes for x in (
            self.mean, self.identity_basis, self.expression_basis,
            self.triangles, self.landmarks, self.face_mask,
        )))

    def shape(self, identity, expression, residual=None):
        vertices = self.mean + np.tensordot(self.identity_basis, identity, axes=(2, 0))
        vertices += np.tensordot(self.expression_basis, expression, axes=(2, 0))
        if residual is not None:
            r = np.asarray(residual, np.float32)
            if r.shape != vertices.shape:
                raise ValueError("residual topology mismatch")
            vertices += r
        return vertices

    @staticmethod
    def project(vertices, parameters, crop_box):
        p = split_faceverse(parameters) if not isinstance(parameters, dict) else parameters
        transformed = np.asarray(vertices, np.float32) @ rotation_matrix(p["angles"])
        transformed += p["translation"]
        transformed[:, 2] += 10.0
        xy = transformed[:, :2] * (1000.0 / transformed[:, 2:3]) + 127.5
        x0, y0, x1, y1 = np.asarray(crop_box, np.float32)
        xy[:, 0] = xy[:, 0] / 256.0 * (x1 - x0) + x0
        xy[:, 1] = xy[:, 1] / 256.0 * (y1 - y0) + y0
        return np.column_stack((xy, transformed[:, 2]))

    def identity_digest(self, identity, residual=None):
        h = hashlib.sha256(np.asarray(identity, "<f4").tobytes())
        if residual is not None:
            h.update(np.asarray(residual, "<f4").tobytes())
        return h.hexdigest()


def crop_box_from_yunet(box, image_shape):
    x, y, w, h = map(float, box[:4])
    length = max(w, h)
    cx, cy = x + w / 2, y + h / 2
    raw = np.array([cx - .65 * length, cy - .70 * length,
                    cx + .65 * length, cy + .60 * length], np.float32)
    # The official crop pads out-of-image areas. The global box is retained so
    # projection and inverse projection remain in the same coordinate frame.
    return raw


def crop_for_faceverse(image, box):
    import cv2
    x0, y0, x1, y1 = np.rint(box).astype(int)
    out = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    h, w = image.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    out[sy0-y0:sy1-y0, sx0-x0:sx1-x0] = image[sy0:sy1, sx0:sx1]
    return cv2.resize(out, (256, 256), interpolation=cv2.INTER_LINEAR)


def faceverse_input(image, box):
    crop = crop_for_faceverse(image, box)
    # Official network receives PIL RGB ToTensor. OpenCV input is BGR.
    return crop[:, :, ::-1].astype(np.float32).transpose(2, 0, 1)[None] / 255.0


def expression_invariant_landmark_delta(observed, projected):
    """Remove first-order aperture/smile leakage before canonical residual fit."""
    delta = np.asarray(observed, np.float32) - np.asarray(projected, np.float32)
    out = delta.copy()
    # Paired eyelids and lips share their mean displacement. This permits width,
    # placement and intrinsic contour residuals but cannot encode opening.
    for a, b in ((37, 41), (38, 40), (43, 47), (44, 46),
                 (50, 58), (51, 57), (52, 56), (61, 67), (62, 66), (63, 65)):
        mean = (delta[a] + delta[b]) * .5
        out[a] = out[b] = mean
    # Corner vertical smile is expression-owned; horizontal width remains ID.
    out[[48, 54], 1] = (delta[48, 1] + delta[54, 1]) * .5
    return out


def bounded_canonical_residual(model, vertices, projected, observed, iod,
                               parameters, crop_box, max_fraction=.10, rings=4):
    """Fit/diffuse a bounded canonical-3D residual from 68 source landmarks."""
    if iod <= 0:
        raise ValueError("invalid interocular distance")
    d2 = expression_invariant_landmark_delta(observed, projected[model.landmarks, :2])
    bound_px = iod * max_fraction
    norms = np.linalg.norm(d2, axis=1)
    d2 *= np.minimum(1.0, bound_px / np.maximum(norms, 1e-8))[:, None]
    # Local perspective inverse at landmark depth, then undo source rotation.
    p = projected[model.landmarks]
    x0, y0, x1, y1 = np.asarray(crop_box, np.float32)
    crop_scale = np.array([256.0 / (x1 - x0), 256.0 / (y1 - y0)], np.float32)
    camera_delta = np.column_stack((d2 * crop_scale * (p[:, 2:3] / 1000.0), np.zeros(68)))
    params = split_faceverse(parameters) if not isinstance(parameters, dict) else parameters
    residual_lm = camera_delta @ rotation_matrix(params["angles"]).T
    residual = np.zeros_like(vertices, dtype=np.float32)
    weight = np.zeros(len(vertices), np.float32)
    residual[model.landmarks] = residual_lm
    weight[model.landmarks] = 1
    adjacency = [[] for _ in range(len(vertices))]
    for tri in model.triangles:
        a, b, c = map(int, tri)
        adjacency[a].extend((b, c)); adjacency[b].extend((a, c)); adjacency[c].extend((a, b))
    frontier = set(map(int, model.landmarks))
    for ring in range(1, rings + 1):
        nxt = set()
        for v in frontier:
            nxt.update(adjacency[v])
        nxt.difference_update(np.flatnonzero(weight))
        for v in nxt:
            neighbours = [n for n in adjacency[v] if weight[n] > 0]
            if neighbours:
                residual[v] = np.mean(residual[neighbours], axis=0)
                weight[v] = 1.0 / (ring + 1)
                residual[v] *= weight[v]
        frontier = nxt
    # One Laplacian regularization pass, anchors preserved.
    smoothed = residual.copy()
    anchors = set(map(int, model.landmarks))
    for v in np.flatnonzero(weight):
        if int(v) not in anchors and adjacency[v]:
            smoothed[v] = .5 * residual[v] + .5 * np.mean(residual[adjacency[v]], axis=0)
    magnitudes = np.linalg.norm(smoothed, axis=1)
    return smoothed, {
        "coordinate_system": "canonical_3d_surface",
        "expression_invariant_pairs": 10,
        "max_input_displacement_px": float(np.max(np.linalg.norm(d2, axis=1))),
        "bound_px": float(bound_px),
        "active_vertices": int(np.count_nonzero(magnitudes)),
        "max_vertex_magnitude": float(magnitudes.max()),
        "laplacian_regularized": True,
        "not_2d_warp": True,
    }


def triangle_distortion(source, target, triangles):
    s = np.asarray(source)[triangles]
    t = np.asarray(target)[triangles]
    se = np.stack((np.linalg.norm(s[:, 1]-s[:, 0], axis=1),
                   np.linalg.norm(s[:, 2]-s[:, 1], axis=1),
                   np.linalg.norm(s[:, 0]-s[:, 2], axis=1)), axis=1)
    te = np.stack((np.linalg.norm(t[:, 1]-t[:, 0], axis=1),
                   np.linalg.norm(t[:, 2]-t[:, 1], axis=1),
                   np.linalg.norm(t[:, 0]-t[:, 2], axis=1)), axis=1)
    stretch = te / np.maximum(se, 1e-8)
    sa = np.linalg.norm(np.cross(s[:, 1]-s[:, 0], s[:, 2]-s[:, 0]), axis=1) * .5
    ta = np.linalg.norm(np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0]), axis=1) * .5
    ratio = ta / np.maximum(sa, 1e-10)
    sn = np.cross(s[:, 1]-s[:, 0], s[:, 2]-s[:, 0])
    tn = np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0])
    orientation = np.sum(sn * tn, axis=1) <= 0
    source_aspect = se.max(axis=1) / np.maximum(se.min(axis=1), 1e-8)
    target_aspect = te.max(axis=1) / np.maximum(te.min(axis=1), 1e-8)
    aspect_distortion = target_aspect / np.maximum(source_aspect, 1e-8)
    def quantiles(x):
        return {str(q): float(np.quantile(x, q)) for q in (0, .01, .05, .5, .95, .99, 1)}
    return {
        "triangles": int(len(triangles)),
        "local_area_ratio": quantiles(ratio),
        "edge_stretch": quantiles(stretch.reshape(-1)),
        "triangle_aspect_distortion": quantiles(aspect_distortion),
        "orientation_failures": int(orientation.sum()),
        "degenerate_triangles": int(np.count_nonzero((sa < 1e-10) | (ta < 1e-10))),
    }


def projected_surface_validity(projected, triangles, side=256):
    """Projected orientation and silhouette continuity without texture/render."""
    import cv2
    p = np.asarray(projected, np.float32)
    xy = p[:, :2]
    lo, hi = xy.min(0), xy.max(0)
    scale = (side - 4) / max(float(np.max(hi - lo)), 1e-8)
    q = (xy - lo) * scale + 2
    tri = q[triangles]
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    signed = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    nondegenerate = np.abs(signed) > 1e-5
    dominant = 1 if np.count_nonzero(signed[nondegenerate] > 0) >= np.count_nonzero(signed[nondegenerate] < 0) else -1
    inverted = nondegenerate & (np.sign(signed) != dominant)
    mask = np.zeros((side, side), np.uint8)
    for points in tri[nondegenerate]:
        cv2.fillConvexPoly(mask, np.rint(points).astype(np.int32), 1)
    components, _ = cv2.connectedComponents(mask, 8)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0 if hierarchy is None else int(np.count_nonzero(hierarchy[0, :, 3] >= 0))
    return {
        "visible_projection_triangles": int(np.count_nonzero(nondegenerate)),
        "projected_back_facing_triangles": int(np.count_nonzero(inverted)),
        "silhouette_components": int(max(0, components - 1)),
        "silhouette_holes": holes,
        "silhouette_continuous": bool(components == 2 and holes == 0),
    }
