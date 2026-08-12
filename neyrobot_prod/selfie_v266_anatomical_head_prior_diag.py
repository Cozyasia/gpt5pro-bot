# -*- coding: utf-8 -*-
"""V266 anatomical head-prior cleanup for the isolated Face Swap diagnostic.

The V265c test proved that source identity transfer is now strong enough, but its
OpenCV matte can still admit rectangular/source-background islands around the
hair and temples.  V266 keeps the low-memory V265c segmentation and adds one
final deterministic anatomical silhouette gate around the detected source face.

Goals:
- keep the source face, forehead and hairstyle;
- reject source-room/cabinet/background pixels that survived GrabCut;
- keep target body and target background untouched;
- avoid rembg/U2NET/ONNX and preserve the Render memory fix;
- retain A/B/C diagnostics, with B conservative and C stronger.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265

VERSION = "v266-anatomical-head-prior-2026-08-13"
_INSTALLED = False
_ORIGINAL_FOREGROUND_MASK = v265._foreground_mask
_ORIGINAL_OVERLAY = v265._clean_head_overlay


def _anatomical_prior(size: tuple[int, int], face_box: tuple[int, int, int, int], *, strong: bool) -> Any:
    """Soft head-shaped prior derived only from the detected face geometry."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    x, y, fw, fh = [float(v) for v in face_box]
    cx = x + fw * 0.50

    # Strong mode is allowed a little more hair volume, but never a rectangular
    # patch.  The jaw is deliberately narrower than the forehead/temples.
    side = 0.60 if strong else 0.56
    top_side = 0.50 if strong else 0.47
    top_y = y - fh * (0.62 if strong else 0.58)
    jaw_y = y + fh * 1.10

    pts = [
        (cx - top_side * fw * 0.72, top_y),
        (cx + top_side * fw * 0.72, top_y),
        (cx + top_side * fw,       top_y + fh * 0.13),
        (cx + side * fw,           y + fh * 0.18),
        (cx + side * fw * 0.96,    y + fh * 0.58),
        (cx + side * fw * 0.72,    y + fh * 0.90),
        (cx + fw * 0.24,           y + fh * 1.05),
        (cx,                       jaw_y),
        (cx - fw * 0.24,           y + fh * 1.05),
        (cx - side * fw * 0.72,    y + fh * 0.90),
        (cx - side * fw * 0.96,    y + fh * 0.58),
        (cx - side * fw,           y + fh * 0.18),
        (cx - top_side * fw,       top_y + fh * 0.13),
    ]
    pts = [
        (max(0, min(w - 1, int(round(px)))), max(0, min(h - 1, int(round(py)))))
        for px, py in pts
    ]

    prior = Image.new("L", (w, h), 0)
    ImageDraw.Draw(prior).polygon(pts, fill=255)
    # Small feather only; enough to remove a cut-out edge without producing the
    # broad cloudy halo visible in earlier V262/V264 experiments.
    return prior.filter(ImageFilter.GaussianBlur(2.2 if strong else 2.6))


def _foreground_mask(
    source_img: Any,
    source_face_box: tuple[int, int, int, int],
    *,
    strong: bool = False,
) -> Any:
    """V265c segmentation intersected with a deterministic anatomical prior."""
    import numpy as np
    from PIL import Image, ImageFilter

    base = _ORIGINAL_FOREGROUND_MASK(source_img, source_face_box, strong=strong).convert("L")
    prior = _anatomical_prior(source_img.size, source_face_box, strong=strong).convert("L")

    ba = np.asarray(base, dtype=np.float32) / 255.0
    pa = np.asarray(prior, dtype=np.float32) / 255.0
    alpha = ba * pa

    # Guarantee the central facial identity core even if GrabCut has a tiny gap,
    # while still respecting the anatomical prior.  This does not expand into
    # source background because the core is strictly inside the face box.
    w, h = source_img.size
    x, y, fw, fh = [float(v) for v in source_face_box]
    yy, xx = np.ogrid[:h, :w]
    cx = x + fw * 0.50
    cy = y + fh * 0.53
    core = (((xx - cx) / max(8.0, fw * 0.48)) ** 2 + ((yy - cy) / max(10.0, fh * 0.58)) ** 2 <= 1.0).astype(np.float32)
    alpha = np.maximum(alpha, core * pa * 0.995)

    out = Image.fromarray(np.clip(alpha * 255.0, 0, 255).astype(np.uint8), "L")
    return out.filter(ImageFilter.GaussianBlur(0.35))


def _overlay(**kwargs: Any) -> tuple[bytes, dict[str, Any]]:
    payload, metrics = _ORIGINAL_OVERLAY(**kwargs)
    metrics = dict(metrics or {})
    strong = bool(float(kwargs.get("outer_strength", 0.0)) >= 0.85)
    metrics["mode"] = "v266_anatomical_head_prior"
    metrics["segmentation"] = (
        "opencv_v265c_plus_anatomical_prior_strong" if strong
        else "opencv_v265c_plus_anatomical_prior_medium"
    )
    metrics["source_background_rejection"] = "anatomical_soft_polygon"
    return payload, metrics


def install() -> bool:
    global _INSTALLED
    # Let V265c install its stable Telegram ownership first, then replace only
    # the matte and full-head compositor used by that diagnostic.
    v265.install()
    v265._foreground_mask = _foreground_mask
    v262._full_head_overlay = _overlay

    media = v262.media
    setattr(media, "_v266_anatomical_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v266_anatomical_head_prior status=installed version=%s", VERSION)
    return True


# Preserve the public media object expected by the bootstrap.
media = v262.media


__all__ = ["VERSION", "media", "install"]
