"""Offline source-photo measurements; NOT a production acceptance gate.

One eye-line similarity removes roll, uniform scale and translation. No fit to
nose/mouth/jaw and no separate eye registration is permitted. Yaw, pitch,
occlusion and expression are NOT solved by this normalization. Callers must not
interpret a low score as human acceptance or extrapolate a calibrated pose domain.
"""

from __future__ import annotations
import numpy as np
import cv2

REGIONS = {
    "all68": tuple(range(68)),
    "inner_face": tuple(range(17, 68)) + (7, 8, 9),
    "outline": tuple(range(17)),
    "mouth": tuple(range(48, 68)),
    "central_chin": (7, 8, 9),
    "nose": tuple(range(27, 36)),
    "eyes": tuple(range(36, 48)),
    "lower_face": tuple(range(4, 13)) + tuple(range(48, 68)),
}


def eye_frame(points):
    p = np.asarray(points, dtype=np.float64)
    if p.shape != (68, 2) or not np.isfinite(p).all():
        raise ValueError("expected finite 68x2 landmarks")
    a, b = p[36:42].mean(0), p[42:48].mean(0)
    delta = b - a
    distance = float(np.linalg.norm(delta))
    if distance <= 1e-6:
        raise ValueError("degenerate eye baseline")
    u = delta / distance
    v = np.array([-u[1], u[0]])
    linear = np.stack([u, v]) / distance
    return np.column_stack([linear, -linear @ ((a + b) * 0.5)])


def normalize(points):
    m = eye_frame(points)
    return np.asarray(points) @ m[:, :2].T + m[:, 2]


def morphology(source_points, candidate_points):
    a, b = normalize(source_points), normalize(candidate_points)
    return {
        name: float(np.linalg.norm(a[list(ids)] - b[list(ids)], axis=1).mean())
        for name, ids in REGIONS.items()
    }


def canonical_crop(image, points):
    # 160px interocular distance; fixed source-relative grid for both eyes/face.
    m = eye_frame(points) * 160
    m[:, 2] += np.array([160.0, 120.0])
    crop = cv2.warpAffine(image, m, (320, 400), flags=cv2.INTER_LINEAR)
    valid = cv2.warpAffine(
        np.ones(image.shape[:2], np.uint8), m, (320, 400), flags=cv2.INTER_NEAREST
    )
    return crop, valid


def appearance(source, candidate, source_points, candidate_points):
    a, va = canonical_crop(source, source_points)
    b, vb = canonical_crop(candidate, candidate_points)
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float64) / 255
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float64) / 255
    result = {}
    # Same global frame, fixed rectangles. Do not re-register eyelids or iris.
    for name, (x0, y0, x1, y1) in {
        "eye_left": (40, 85, 120, 145),
        "eye_right": (200, 85, 280, 145),
    }.items():
        if not (va[y0:y1, x0:x1].all() and vb[y0:y1, x0:x1].all()):
            raise ValueError("eye appearance crop outside image")
        s = a[y0:y1, x0:x1]
        t = b[y0:y1, x0:x1]
        yy, xx = np.mgrid[-1 : 1 : complex(s.shape[0]), -1 : 1 : complex(s.shape[1])]
        # Remove only photometric gain/bias and a planar light field. No spatial warp.
        design = np.column_stack([s.ravel(), np.ones(s.size), xx.ravel(), yy.ravel()])
        weights = np.linalg.lstsq(design, t.ravel(), rcond=None)[0]
        fitted = (design @ weights).reshape(s.shape)
        if s.std() < 0.01 or not 0.25 < weights[0] < 4:
            raise ValueError("unmeasurable eye contrast or light shift")
        result[name + "_appearance"] = float(
            np.sqrt(np.mean((t - fitted) ** 2)) / s.std()
        )
        sg = np.stack(np.gradient(fitted))
        tg = np.stack(np.gradient(t))
        result[name + "_gradient"] = float(
            np.sqrt(np.mean((tg - sg) ** 2)) / max(np.sqrt(np.mean(sg**2)), 1e-6)
        )
    return result


def measured_limits(rows):
    """Observed calibration envelope, without a hand-chosen safety multiplier.

    Not a population guarantee: independent held-out sources, poses, expressions
    and human-labelled generations are required before any production use.
    """
    if not rows:
        raise ValueError("empty calibration")
    keys = set(rows[0])
    if not keys or any(set(row) != keys for row in rows):
        raise ValueError("inconsistent channels")
    if any(not np.isfinite(v) or v < 0 for row in rows for v in row.values()):
        raise ValueError("invalid calibration")
    return {k: max(float(r[k]) for r in rows) for k in sorted(keys)}


def compare_limits(measurements, limits):
    if set(measurements) != set(limits) or not limits:
        raise ValueError("missing channels")
    if any(
        not np.isfinite(v) or v < 0
        for row in (measurements, limits)
        for v in row.values()
    ):
        raise ValueError("invalid evidence")
    return [k for k in sorted(limits) if measurements[k] > limits[k]]
