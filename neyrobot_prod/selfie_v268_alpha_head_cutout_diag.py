# -*- coding: utf-8 -*-
"""V268 alpha head cutout for the isolated Face Swap diagnostic.

V267 still allowed source-background slabs because it intersected GrabCut with a
head-shaped gate: pixels *inside* the gate could still be source room/background.
V268 changes the operation: build an explicit head alpha matte from face geometry,
warp only that RGBA head, and feather the alpha edge onto the target/baseline.

This is deliberately a deterministic low-memory Pillow/OpenCV compositor.  It
keeps target body/background untouched outside the head alpha and avoids the
rectangular crop semantics that caused V265-V267 artifacts.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v268-alpha-head-cutout-2026-08-13"
_INSTALLED = False


def _head_alpha(size: tuple[int, int], face_box: tuple[int, int, int, int], *, strong: bool) -> Any:
    """Create a continuous head/hair alpha; zero means source pixels can never leak."""
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    w, h = size
    x, y, fw, fh = [float(v) for v in face_box]
    cx = x + fw * 0.50
    mask = np.zeros((h, w), np.uint8)

    # Hair/cranium.  Slightly wider in C, but always curved and never crop-shaped.
    cv2.ellipse(mask, (round(cx), round(y + fh * 0.08)),
                (round(fw * (0.56 if strong else 0.535)), round(fh * (0.70 if strong else 0.67))),
                0, 0, 360, 255, -1)
    # Face/cheeks.
    cv2.ellipse(mask, (round(cx), round(y + fh * 0.54)),
                (round(fw * (0.515 if strong else 0.50)), round(fh * 0.59)),
                0, 0, 360, 255, -1)
    # Tapered jaw/chin: intentionally no neck/background rectangle.
    pts = np.array([
        [cx - fw * 0.40, y + fh * 0.72],
        [cx + fw * 0.40, y + fh * 0.72],
        [cx + fw * 0.29, y + fh * 0.98],
        [cx + fw * 0.16, y + fh * 1.075],
        [cx,             y + fh * 1.105],
        [cx - fw * 0.16, y + fh * 1.075],
        [cx - fw * 0.29, y + fh * 0.98],
    ], np.float32)
    pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
    pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)
    cv2.fillConvexPoly(mask, np.round(pts).astype(np.int32), 255)

    # Feather only a narrow boundary.  Interior remains fully opaque, so hair has
    # no holes; exterior remains zero, so source room/cabinet cannot be pasted.
    alpha = Image.fromarray(mask, "L")
    return alpha.filter(ImageFilter.GaussianBlur(3.2 if strong else 3.8))


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image

    source = fs.image(source_full_raw).convert("RGB")
    target = fs.image(target_full_raw).convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")
    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    if min(sw, sh, tw, th) < 64:
        raise ValueError("face region is too small for V268 head cutout")

    strong = bool(outer_strength >= 0.85)
    W, H = target.size
    # Destination patch only bounds computation; alpha, not the rectangle, owns pixels.
    l = max(0, int(round(tx - tw * 0.24)))
    r = min(W, int(round(tx + tw * 1.24)))
    t = max(0, int(round(ty - th * 0.64)))
    b = min(H, int(round(ty + th * 1.12)))
    pw, ph = r - l, b - t

    scale = 0.5 * ((sw / tw) + (sh / th))
    c = sx + (l - tx) * scale
    f = sy + (t - ty) * scale
    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    a_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source.transform((pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
                              resample=rgb_resample, fillcolor=(0, 0, 0))
    alpha_src = _head_alpha(source.size, source_face_box, strong=strong)
    alpha = alpha_src.transform((pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
                                resample=a_resample, fillcolor=0)

    # Match source head gently to target lighting before alpha compositing.
    reference = baseline.crop((l, t, r, b))
    warped = v262._color_match(warped, reference, amount=0.16 if strong else 0.20)

    aa = np.asarray(alpha, np.float32) / 255.0
    # Fade the final chin pixels into the target neck.  This is an alpha fade, not
    # a source-background band, so the target remains visible through the seam.
    local_face_y = ty - t
    chin0 = max(0, min(ph, int(round(local_face_y + th * 0.96))))
    chin1 = max(chin0 + 1, min(ph, int(round(local_face_y + th * 1.105))))
    if chin1 > chin0:
        aa[chin0:chin1] *= np.linspace(1.0, 0.0, chin1 - chin0, dtype=np.float32)[:, None]
    aa[chin1:] = 0.0
    alpha = Image.fromarray(np.clip(aa * 255.0, 0, 255).astype(np.uint8), "L")

    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=97)
    return payload, {
        "mode": "v268_alpha_head_cutout",
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "deterministic_continuous_head_alpha",
        "source_background_rejection": "zero_alpha_outside_head",
        "edge_blend": "narrow_gaussian_plus_chin_fade",
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v268_alpha_head_owned", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v268_alpha_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v268_alpha_head_cutout status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
