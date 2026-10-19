"""Commercially-clear L2-C geometry prototype based on MediaPipe topology.

No FaceVerse/BFM/FLAME/CelebAMask assets are loaded here.  Intrinsic identity
is a bounded canonical 3-D surface residual.  Expression is an explicit sparse
subspace, so the stored identity residual is algebraically orthogonal to it.
"""

from __future__ import annotations

import hashlib
import numpy as np


RIGID = np.array([1, 4, 33, 133, 263, 362, 168, 234, 454], np.int32)
MOUTH_UPPER = np.array([61,185,40,39,37,0,267,269,270,409,291,78,191,80,81,82,13,312,311,310,415,308])
MOUTH_LOWER = np.array([61,146,91,181,84,17,314,405,321,375,291,78,95,88,178,87,14,317,402,318,324,308])
LEFT_EYE_UPPER = np.array([33,246,161,160,159,158,157,173,133])
LEFT_EYE_LOWER = np.array([33,7,163,144,145,153,154,155,133])
RIGHT_EYE_UPPER = np.array([362,398,384,385,386,387,388,466,263])
RIGHT_EYE_LOWER = np.array([362,382,381,380,374,373,390,249,263])
LEFT_BROW = np.array([70,63,105,66,107,55,65,52,53,46])
RIGHT_BROW = np.array([336,296,334,293,300,285,295,282,283,276])


def load_canonical_obj(path):
    vertices, triangles = [], []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("v "):
                vertices.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                triangles.append([int(x.split("/")[0]) - 1 for x in line.split()[1:4]])
    return np.asarray(vertices, np.float32), np.asarray(triangles, np.int32)


def _umeyama(source, target):
    source, target = np.asarray(source, np.float64), np.asarray(target, np.float64)
    sm, tm = source.mean(0), target.mean(0)
    sx, tx = source - sm, target - tm
    u, s, vt = np.linalg.svd(sx.T @ tx / len(source))
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    scale = float(s.sum() / np.maximum(np.mean(np.sum(sx * sx, axis=1)), 1e-12))
    translation = tm - scale * sm @ rotation
    return scale, rotation.astype(np.float32), translation.astype(np.float32)


def observed_xyz(landmarks):
    p = np.asarray(landmarks, np.float32).copy()
    p[:, 1:] *= -1  # canonical model uses +Y up; MediaPipe image coordinates do not.
    return p


def canonicalize(template, observed):
    scale, rotation, translation = _umeyama(template[RIGID], observed_xyz(observed)[RIGID])
    canonical = ((observed_xyz(observed) - translation) @ rotation.T) / scale
    return canonical.astype(np.float32), (scale, rotation, translation)


def project(canonical, transform):
    scale, rotation, translation = transform
    out = scale * np.asarray(canonical) @ rotation + translation
    out[:, 1:] *= -1
    return out.astype(np.float32)


def expression_basis(template):
    """Fixed geometric modes; no learned/research-only weights or datasets."""
    n = len(template)
    modes = []
    def mode(groups):
        x = np.zeros((n, 3), np.float32)
        for indices, vector in groups:
            x[indices] += np.asarray(vector, np.float32)
        modes.append(x.reshape(-1))
    mode(((MOUTH_UPPER, (0, .5, 0)), (MOUTH_LOWER, (0, -.5, 0)))) # opening
    mode((((np.array([61,78])), (-.6, .5, 0)), (np.array([291,308]), (.6, .5, 0)))) # smile
    mode(((MOUTH_UPPER, (0, 0, .3)), (MOUTH_LOWER, (0, 0, .3)))) # protrusion
    mode(((MOUTH_UPPER, (0, -.25, 0)), (MOUTH_LOWER, (0, .25, 0)))) # compression
    mode(((LEFT_EYE_UPPER, (0, .5, 0)), (LEFT_EYE_LOWER, (0, -.5, 0))))
    mode(((RIGHT_EYE_UPPER, (0, .5, 0)), (RIGHT_EYE_LOWER, (0, -.5, 0))))
    mode(((LEFT_BROW, (0, .6, 0)),))
    mode(((RIGHT_BROW, (0, .6, 0)),))
    q, _ = np.linalg.qr(np.stack(modes, axis=1))
    return q.astype(np.float32)


def fit_identity(template, source_canonical, max_fraction=.18):
    q = expression_basis(template)
    raw = (np.asarray(source_canonical) - template).reshape(-1)
    expression = q @ (q.T @ raw)
    identity = (raw - expression).reshape(-1, 3)
    iod = float(np.linalg.norm(template[33] - template[263]))
    bound = iod * max_fraction
    mag = np.linalg.norm(identity, axis=1)
    identity *= np.minimum(1.0, bound / np.maximum(mag, 1e-8))[:, None]
    return identity.astype(np.float32), expression.reshape(-1, 3).astype(np.float32), q


def retarget(template, identity, q, target_canonical):
    target_delta = (np.asarray(target_canonical) - template).reshape(-1)
    target_expression = (q @ (q.T @ target_delta)).reshape(-1, 3)
    return (template + identity + target_expression).astype(np.float32), target_expression.astype(np.float32)


def residual_digest(identity):
    return hashlib.sha256(np.asarray(identity, "<f4").tobytes()).hexdigest()


def topology_metrics(source, target, triangles):
    s, t = np.asarray(source)[triangles], np.asarray(target)[triangles]
    sn = np.cross(s[:, 1] - s[:, 0], s[:, 2] - s[:, 0])
    tn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    sa, ta = np.linalg.norm(sn, axis=1) / 2, np.linalg.norm(tn, axis=1) / 2
    se = np.linalg.norm(s[:, [1,2,0]] - s[:, [0,1,2]], axis=2)
    te = np.linalg.norm(t[:, [1,2,0]] - t[:, [0,1,2]], axis=2)
    area = ta / np.maximum(sa, 1e-8)
    stretch = te / np.maximum(se, 1e-8)
    orient = np.sum(sn * tn, axis=1) <= 0
    return {
        "triangles": int(len(triangles)),
        "orientation_failures": int(orient.sum()),
        "area_ratio_min": float(area.min()), "area_ratio_max": float(area.max()),
        "edge_stretch_min": float(stretch.min()), "edge_stretch_max": float(stretch.max()),
    }


def semantic_metrics(points):
    p = np.asarray(points)
    iod = max(float(np.linalg.norm(p[33, :2] - p[263, :2])), 1e-8)
    mouth_width = float(np.linalg.norm(p[61, :2] - p[291, :2]) / iod)
    opening = float(np.linalg.norm(p[13, :2] - p[14, :2]) / iod)
    lip_height = float((np.linalg.norm(p[0,:2]-p[13,:2]) + np.linalg.norm(p[14,:2]-p[17,:2])) / iod)
    philtrum = float(np.linalg.norm(p[2,:2]-p[0,:2]) / iod)
    mouth_chin = float(np.linalg.norm((p[61,:2]+p[291,:2])/2-p[152,:2]) / iod)
    return {"mouth_width":mouth_width,"opening":opening,"lip_height":lip_height,"philtrum":philtrum,"mouth_chin":mouth_chin}
