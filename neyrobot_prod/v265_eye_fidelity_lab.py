"""Offline eye measurement candidates; no image patching or runtime gate."""

import cv2
import numpy as np
from .v265_source_fidelity import canonical_crop


def descriptors(image, points, *, include_face=False, include_profiles=False):
    crop, valid = canonical_crop(image, points)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    out = {}
    rectangles = {"left": (40, 85, 120, 145), "right": (200, 85, 280, 145)}
    if include_face:
        rectangles.update({"nose": (105, 165, 215, 255), "mouth": (70, 250, 250, 345)})
    for side, (x0, y0, x1, y1) in rectangles.items():
        if not valid[y0:y1, x0:x1].all():
            raise ValueError("eye outside image")
        a = gray[y0:y1, x0:x1]
        a = cv2.GaussianBlur(a, (0, 0), 1)
        band = a - cv2.GaussianBlur(a, (0, 0), 5)
        norm = np.linalg.norm(band)
        if norm < 1e-4:
            raise ValueError("unmeasurable eye contrast")
        out[side + "_band"] = (band / norm).ravel()
        if include_profiles and side in ("left", "right"):
            # Fixed global eye frame: no iris-local registration that can hide drift.
            # Central eye band suppresses brows and retains within-HOG-cell shifts.
            central = band[23:47, 15:65]
            energy = np.maximum(-central, 0)
            total = float(energy.sum())
            if total < 1e-6:
                raise ValueError("unmeasurable central-eye structure")
            xprofile = cv2.GaussianBlur(energy.sum(0)[None, :], (0, 0), 1).ravel()
            yprofile = cv2.GaussianBlur(energy.sum(1)[:, None], (0, 0), 1).ravel()
            # Cumulative dark-structure profiles retain displacement, unlike cell sums.
            out[side + "_profile"] = (
                np.r_[np.cumsum(xprofile), np.cumsum(yprofile)] / total
            )
        # Smoothed ordinal comparisons, positive affine photometric invariant.
        center = a[3:-3, 3:-3]
        out[side + "_census"] = np.stack(
            [
                a[3 + dy : a.shape[0] - 3 + dy, 3 + dx : a.shape[1] - 3 + dx] > center
                for dx, dy in [
                    (3, 0),
                    (-3, 0),
                    (0, 3),
                    (0, -3),
                    (2, 2),
                    (-2, 2),
                    (2, -2),
                    (-2, -2),
                ]
            ]
        ).ravel()
        gx = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3)
        mag, ang = cv2.cartToPolar(gx, gy)
        bins = np.floor((ang % np.pi) * 8 / np.pi).astype(int).clip(0, 7)
        hist = []
        for yy in range(0, a.shape[0], 10):
            for xx in range(0, a.shape[1], 10):
                h = np.bincount(
                    bins[yy : yy + 10, xx : xx + 10].ravel(),
                    weights=mag[yy : yy + 10, xx : xx + 10].ravel(),
                    minlength=8,
                )
                hist.extend(h / (np.linalg.norm(h) + 1e-8))
        out[side + "_hog"] = np.asarray(hist)
    return out


def compare(a, b):
    if not a or set(a) != set(b):
        raise ValueError("missing local descriptor evidence")
    result = {}
    for k in a:
        if a[k].shape != b[k].shape or not a[k].size:
            raise ValueError("incompatible local descriptors")
        if not np.isfinite(a[k]).all() or not np.isfinite(b[k]).all():
            raise ValueError("nonfinite local descriptors")
        if k.endswith("census"):
            result[k] = float(np.mean(a[k] != b[k]))
        elif k.endswith("band"):
            result[k] = float(max(0, 1 - np.dot(a[k], b[k])))
        else:
            result[k] = float(np.sqrt(np.mean((a[k] - b[k]) ** 2)))
    return result
