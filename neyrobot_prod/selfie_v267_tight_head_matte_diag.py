# -*- coding: utf-8 -*-
"""V267 tight anatomical head matte for the isolated Face Swap diagnostic.

This iteration fixes the two remaining defects visible in V266:
1) source-background slabs around the ears/jaw;
2) occasional holes through the transferred hairstyle.

It stays on the low-memory OpenCV/Pillow path: no rembg, U2NET or ONNX.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import selfie_v266_anatomical_head_prior_diag as v266

VERSION = "v267-tight-head-matte-2026-08-13"
_INSTALLED = False
_BASE_FOREGROUND_MASK = v266._ORIGINAL_FOREGROUND_MASK
_BASE_OVERLAY = v265._clean_head_overlay


def _tight_geometry(size: tuple[int, int], face_box: tuple[int, int, int, int], *, strong: bool) -> tuple[Any, Any]:
    """Return (full head gate, upper-hair repair gate) as uint8 numpy arrays."""
    import cv2
    import numpy as np

    w, h = size
    x, y, fw, fh = [float(v) for v in face_box]
    cx = x + fw * 0.50

    gate = np.zeros((h, w), dtype=np.uint8)
    hair_gate = np.zeros((h, w), dtype=np.uint8)

    # Hair dome: deliberately tighter laterally than V266's polygon.  It gives
    # enough room for the source hairstyle but cannot become a rectangular slab.
    hair_cy = y - fh * (0.03 if strong else 0.01)
    hair_rx = fw * (0.585 if strong else 0.555)
    hair_ry = fh * (0.73 if strong else 0.69)
    cv2.ellipse(
        gate,
        (int(round(cx)), int(round(hair_cy))),
        (max(2, int(round(hair_rx))), max(2, int(round(hair_ry)))),
        0, 0, 360, 255, -1,
    )
    cv2.ellipse(
        hair_gate,
        (int(round(cx)), int(round(hair_cy))),
        (max(2, int(round(hair_rx * 0.98))), max(2, int(round(hair_ry * 0.98)))),
        0, 0, 360, 255, -1,
    )

    # Face/jaw oval.  This is the important background-rejection constraint:
    # below the temples the allowed region hugs the actual face instead of the
    # rectangular source crop.  Target ears/neck/background therefore survive.
    face_cy = y + fh * 0.53
    face_rx = fw * (0.535 if strong else 0.515)
    face_ry = fh * 0.615
    cv2.ellipse(
        gate,
        (int(round(cx)), int(round(face_cy))),
        (max(2, int(round(face_rx))), max(2, int(round(face_ry)))),
        0, 0, 360, 255, -1,
    )

    # A small tapered chin extension preserves the source jaw without carrying
    # source-room pixels into the neck band.
    chin_top = y + fh * 0.82
    chin_bottom = y + fh * 1.075
    pts = np.array([
        [cx - fw * 0.34, chin_top],
        [cx + fw * 0.34, chin_top],
        [cx + fw * 0.22, chin_bottom],
        [cx,             y + fh * 1.105],
        [cx - fw * 0.22, chin_bottom],
    ], dtype=np.float32)
    pts[:, 0] = np.clip(pts[:, 0], 0, max(0, w - 1))
    pts[:, 1] = np.clip(pts[:, 1], 0, max(0, h - 1))
    cv2.fillConvexPoly(gate, np.round(pts).astype(np.int32), 255)

    return gate, hair_gate


def _foreground_mask(
    source_img: Any,
    source_face_box: tuple[int, int, int, int],
    *,
    strong: bool = False,
) -> Any:
    """Tight V265c segmentation with upper-hair repair and no source-background slabs."""
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    base = np.asarray(
        _BASE_FOREGROUND_MASK(source_img, source_face_box, strong=strong).convert("L"),
        dtype=np.uint8,
    )
    gate, hair_gate = _tight_geometry(source_img.size, source_face_box, strong=strong)

    # Hard reject everything outside anatomical geometry first.
    binary = ((base >= 20) & (gate > 0)).astype(np.uint8)

    # Close narrow cracks in hair, then fill only enclosed holes.  Repair is
    # restricted to the upper-hair gate, so it cannot bring back wall/cabinet.
    k = np.ones((7, 7), np.uint8)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k, iterations=2)
    closed = v265._fill_enclosed_holes(closed, (gate > 0).astype(np.uint8))

    x, y, fw, fh = [float(v) for v in source_face_box]
    upper_limit = int(round(y + fh * 0.48))
    upper_limit = max(0, min(binary.shape[0], upper_limit))
    upper = np.zeros_like(binary)
    upper[:upper_limit, :] = 1

    # Strong mode gets a constrained hull only above mid-face.  This repairs
    # crown holes while keeping side/jaw geometry from the stricter mask.
    if strong:
        contours, _ = cv2.findContours(
            (closed * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if contours:
            contour = max(contours, key=cv2.contourArea)
            hull = cv2.convexHull(contour)
            hull_mask = np.zeros_like(binary)
            cv2.fillConvexPoly(hull_mask, hull, 1)
            repair = hull_mask * upper * (hair_gate > 0).astype(np.uint8)
            closed = np.maximum(closed, repair)

    # Keep repair only in hair; below that retain the original segmented face.
    result = binary.copy()
    hair_region = upper * (hair_gate > 0).astype(np.uint8)
    result = np.where(hair_region > 0, np.maximum(result, closed), result).astype(np.uint8)
    result *= (gate > 0).astype(np.uint8)

    # Guarantee the inner face identity core, but never outside the tight gate.
    h, w = result.shape
    yy, xx = np.ogrid[:h, :w]
    cx = x + fw * 0.50
    cy = y + fh * 0.53
    core = (((xx - cx) / max(8.0, fw * 0.47)) ** 2 + ((yy - cy) / max(10.0, fh * 0.57)) ** 2 <= 1.0)
    result = np.maximum(result, (core & (gate > 0)).astype(np.uint8))

    out = Image.fromarray((result * 255).astype(np.uint8), "L")
    return out.filter(ImageFilter.GaussianBlur(0.75 if strong else 0.90))


def _overlay(**kwargs: Any) -> tuple[bytes, dict[str, Any]]:
    payload, metrics = _BASE_OVERLAY(**kwargs)
    metrics = dict(metrics or {})
    strong = bool(float(kwargs.get("outer_strength", 0.0)) >= 0.85)
    metrics["mode"] = "v267_tight_head_matte"
    metrics["segmentation"] = (
        "opencv_v265c_tight_geometry_hair_hull" if strong
        else "opencv_v265c_tight_geometry_hair_close"
    )
    metrics["source_background_rejection"] = "tight_hair_face_chin_geometry"
    metrics["hair_hole_repair"] = "upper_only"
    return payload, metrics


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v267_tight_head_owned", False):
        return True

    # Install the stable V265/V262 media owner once, then replace only the matte
    # and compositor.  Repeated bootstrap stabilization calls become no-ops.
    v265.install()
    v265._foreground_mask = _foreground_mask
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v267_tight_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v267_tight_head_matte status=installed version=%s", VERSION)
    return True


media = v262.media

__all__ = ["VERSION", "media", "install"]
