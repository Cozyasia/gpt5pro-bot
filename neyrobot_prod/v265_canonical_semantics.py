"""Offline semantic ownership for canonical L.

Landmark regions are deterministic geometry labels.  The accessory detector is
an intentionally lightweight edge/appearance hypothesis and is reported as
such; it is not silently promoted to verified segmentation.
"""

import numpy as np


REGIONS = (
    "forehead",
    "eyebrows",
    "eyes_eyelids",
    "nose",
    "cheeks",
    "upper_lip",
    "lower_lip",
    "mouth_interior",
    "jaw",
    "chin",
    "accessories",
    "occlusion",
    "unknown",
)
CRITICAL = REGIONS[:10]


def _finite_landmarks(value):
    p = np.asarray(value, dtype=np.float32)
    if p.shape != (68, 2) or not np.isfinite(p).all():
        raise ValueError("expected finite 68-point landmarks")
    return p


def _ellipse(xx, yy, centre, radii):
    rx, ry = np.maximum(np.asarray(radii, float), 1.0)
    return ((xx - centre[0]) / rx) ** 2 + ((yy - centre[1]) / ry) ** 2 <= 1


def semantic_region_map(shape, landmarks, face_mask, *, accessory=None, occluded=None):
    """Classify a face-support raster into explicit product ownership regions."""
    h, w = map(int, shape[:2])
    p = _finite_landmarks(landmarks)
    face = np.asarray(face_mask)
    if face.shape != (h, w) or face.dtype != np.bool_:
        raise ValueError("explicit boolean face support required")
    accessory = np.zeros((h, w), bool) if accessory is None else np.asarray(accessory)
    occluded = np.zeros((h, w), bool) if occluded is None else np.asarray(occluded)
    if accessory.shape != face.shape or accessory.dtype != np.bool_:
        raise ValueError("explicit boolean accessory mask required")
    if occluded.shape != face.shape or occluded.dtype != np.bool_:
        raise ValueError("explicit boolean occlusion mask required")
    yy, xx = np.indices((h, w))
    labels = np.full((h, w), REGIONS.index("unknown"), np.uint8)
    eye_left, eye_right = p[36:42].mean(0), p[42:48].mean(0)
    iod = max(float(np.linalg.norm(eye_right - eye_left)), 1.0)
    mouth = p[48:68]
    mouth_c = mouth.mean(0)
    mouth_rx = max(float(np.ptp(mouth[:, 0])) * 0.58, iod * 0.18)
    mouth_ry = max(float(np.ptp(mouth[:, 1])) * 0.75, iod * 0.07)
    interior = _ellipse(xx, yy, p[60:68].mean(0), [mouth_rx * 0.55, mouth_ry * 0.45])
    lip = _ellipse(xx, yy, mouth_c, [mouth_rx, mouth_ry]) & ~interior
    upper_lip = lip & (yy <= mouth_c[1])
    lower_lip = lip & (yy > mouth_c[1])
    eyes = _ellipse(xx, yy, eye_left, [iod * 0.24, iod * 0.115]) | _ellipse(
        xx, yy, eye_right, [iod * 0.24, iod * 0.115]
    )
    brow_y = float(p[17:27, 1].mean())
    brows = (
        (yy >= brow_y - iod * 0.13)
        & (yy <= brow_y + iod * 0.10)
        & (xx >= p[17:27, 0].min() - iod * 0.08)
        & (xx <= p[17:27, 0].max() + iod * 0.08)
        & ~eyes
    )
    nose = (
        (yy >= p[27:36, 1].min() - iod * 0.06)
        & (yy <= p[27:36, 1].max() + iod * 0.12)
        & (xx >= p[31:36, 0].min() - iod * 0.13)
        & (xx <= p[31:36, 0].max() + iod * 0.13)
    )
    chin_y = float(p[8, 1])
    chin = _ellipse(xx, yy, [(p[7, 0] + p[9, 0]) / 2, chin_y], [iod * 0.34, iod * 0.25])
    jaw = (
        (yy >= mouth_c[1] + iod * 0.16)
        & (yy <= p[:17, 1].max() + iod * 0.05)
        & ~chin
    )
    forehead = yy < brow_y - iod * 0.08
    order = (
        ("forehead", forehead),
        ("eyebrows", brows),
        ("eyes_eyelids", eyes),
        ("nose", nose),
        ("upper_lip", upper_lip),
        ("lower_lip", lower_lip),
        ("mouth_interior", interior),
        ("jaw", jaw),
        ("chin", chin),
    )
    labels[face] = REGIONS.index("cheeks")
    for name, mask in order:
        labels[face & mask] = REGIONS.index(name)
    labels[face & accessory] = REGIONS.index("accessories")
    labels[face & occluded] = REGIONS.index("occlusion")
    labels[~face] = REGIONS.index("unknown")
    return labels


def accessory_edge_hypothesis(image, landmarks):
    """Detect probable spectacle-frame pixels; never claim verified segmentation."""
    im = np.asarray(image)
    p = _finite_landmarks(landmarks)
    if im.ndim != 3 or im.shape[2] != 3 or im.dtype != np.uint8:
        raise ValueError("expected uint8 image")
    h, w = im.shape[:2]
    gray = im.astype(np.float32).mean(2)
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:] = np.abs(np.diff(gray, axis=1))
    gy[1:] = np.abs(np.diff(gray, axis=0))
    edge = np.maximum(gx, gy)
    iod = max(float(np.linalg.norm(p[42:48].mean(0) - p[36:42].mean(0))), 1.0)
    x0 = max(0, int(np.floor(p[36:48, 0].min() - iod * 0.22)))
    x1 = min(w, int(np.ceil(p[36:48, 0].max() + iod * 0.22)))
    y0 = max(0, int(np.floor(min(p[17:27, 1].min(), p[36:48, 1].min()) - iod * 0.08)))
    y1 = min(h, int(np.ceil(p[36:48, 1].max() + iod * 0.24)))
    band = np.zeros((h, w), bool)
    band[y0:y1, x0:x1] = True
    values = edge[band]
    if not len(values):
        raise ValueError("empty accessory search band")
    threshold = max(22.0, float(np.percentile(values, 86)))
    dark = gray <= np.percentile(gray[band], 55)
    candidate = band & dark & (edge >= threshold)
    # Small fixed dilation joins one-pixel frame edges without swallowing eyes.
    mask = candidate.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        mask |= np.roll(candidate, (dy, dx), (0, 1))
    mask &= band
    left = mask[:, : int((p[39, 0] + p[42, 0]) / 2)].sum()
    right = mask[:, int((p[39, 0] + p[42, 0]) / 2) :].sum()
    minimum = max(6, int(iod * 0.12))
    present = bool(left >= minimum and right >= minimum)
    return {
        "mask": mask,
        "present": present,
        "candidate_pixels": int(mask.sum()),
        "search_pixels": int(band.sum()),
        "confidence": float(min(left, right) / max(minimum, 1)),
        "segmentation_verified": False,
        "method": "landmark_bounded_dark_edge_hypothesis",
    }


def accessory_policy(source_present, target_present):
    if source_present and not target_present:
        return {"action": "controlled_failure", "compatible": False}
    if target_present:
        return {"action": "retain_target_accessory_layer", "compatible": True}
    return {"action": "no_accessory_layer", "compatible": True}


def completeness_report(region_map, source_replaced, expression_owned):
    labels = np.asarray(region_map)
    source = np.asarray(source_replaced)
    expression = np.asarray(expression_owned)
    if source.shape != labels.shape or expression.shape != labels.shape:
        raise ValueError("incompatible completeness evidence")
    if source.dtype != np.bool_ or expression.dtype != np.bool_:
        raise ValueError("boolean ownership evidence required")
    rows = {}
    for index, name in enumerate(REGIONS):
        mask = labels == index
        rows[name] = {
            "pixels": int(mask.sum()),
            "source_owned": int((mask & source).sum()),
            "expression_or_occlusion_owned": int((mask & expression).sum()),
            "target_unresolved": int((mask & ~source & ~expression).sum()),
        }
    missing = {
        name: rows[name]["target_unresolved"]
        for name in CRITICAL
        if rows[name]["target_unresolved"]
    }
    return {
        "regions": rows,
        "critical_target_unresolved": missing,
        "critical_pixels": int(sum(rows[n]["pixels"] for n in CRITICAL)),
        "identity_complete": not missing,
    }
