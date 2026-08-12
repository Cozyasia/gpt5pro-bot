# -*- coding: utf-8 -*-
"""V265 low-memory full-head transplant diagnostic.

V265c keeps the successful seeded OpenCV path from V265b, but fixes the failure
visible in test 01533980d9d4: background leakage was removed, yet GrabCut plus
opening/erosion punched large holes through the source hair.  The revised matte:

1) uses the same anatomical face seed and connected-component rejection;
2) fills only enclosed holes inside the selected head component;
3) repairs the upper-hair region with a constrained convex hull for strong mode;
4) never reintroduces rembg/U2NET/ONNX, so Render RAM stays bounded;
5) keeps B conservative and makes C the stronger silhouette-repair diagnostic.

The isolated Face Swap test still returns A/B/C. Production AI-selfie is not
changed by this module.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v265c-hole-filled-hair-silhouette-2026-08-12"
_INSTALLED = False


def _fill_enclosed_holes(mask: Any, allowed: Any) -> Any:
    """Fill enclosed background islands without growing beyond allowed geometry."""
    import cv2
    import numpy as np

    binary = (mask > 0).astype(np.uint8)
    inv = (1 - binary).astype(np.uint8)
    h, w = inv.shape
    flood = inv.copy()
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)

    # Flood all border-connected background. What remains in `inv` afterwards is
    # an enclosed hole in the selected head component.
    for px, py in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flood[py, px]:
            cv2.floodFill(flood, flood_mask, (px, py), 0)
    holes = (flood > 0).astype(np.uint8)
    holes *= allowed.astype(np.uint8)
    return np.maximum(binary, holes)


def _foreground_mask(
    source_img: Any,
    source_face_box: tuple[int, int, int, int],
    *,
    strong: bool = False,
) -> Any:
    """Return a low-memory, hole-repaired 8-bit head matte."""
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    rgb = np.asarray(source_img.convert("RGB"), dtype=np.uint8)
    h, w = rgb.shape[:2]
    x, y, fw, fh = [int(v) for v in source_face_box]

    x1 = max(0, int(round(x - fw * 0.30)))
    y1 = max(0, int(round(y - fh * 0.64)))
    x2 = min(w, int(round(x + fw * 1.30)))
    y2 = min(h, int(round(y + fh * 1.16)))
    rw, rh = x2 - x1, y2 - y1
    if rw < 64 or rh < 80:
        raise ValueError("source head region is too small for OpenCV mask")

    crop = cv2.cvtColor(rgb[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
    mask = np.full((rh, rw), cv2.GC_BGD, dtype=np.uint8)
    yy, xx = np.ogrid[:rh, :rw]

    cx = (x + fw * 0.50) - x1
    cy = (y + fh * 0.39) - y1
    rx = max(8.0, fw * 0.73)
    ry = max(10.0, fh * 1.00)
    head_oval = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    mask[head_oval] = cv2.GC_PR_FGD

    fcx = (x + fw * 0.50) - x1
    fcy = (y + fh * 0.54) - y1
    frx = max(6.0, fw * 0.40)
    fry = max(8.0, fh * 0.46)
    face_seed = ((xx - fcx) / frx) ** 2 + ((yy - fcy) / fry) ** 2 <= 1.0
    mask[face_seed] = cv2.GC_FGD

    srx = max(4.0, fw * 0.22)
    sry = max(5.0, fh * 0.25)
    center_seed = ((xx - fcx) / srx) ** 2 + ((yy - fcy) / sry) ** 2 <= 1.0

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(crop, mask, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
        fg = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0
        ).astype(np.uint8)
    except cv2.error:
        fg = head_oval.astype(np.uint8)

    # Keep only foreground physically connected to the central face seed.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    keep = np.zeros_like(fg)
    seed_labels = [int(v) for v in np.unique(labels[center_seed]) if int(v) != 0]
    if seed_labels:
        for lab in seed_labels:
            keep[labels == lab] = 1
    elif n > 1:
        lab = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        keep[labels == lab] = 1
    else:
        keep = fg

    keep *= head_oval.astype(np.uint8)

    # V265b's erosion/opening was the source of the dramatic holes through the
    # hairstyle.  Close first, then fill true enclosed islands.  No erosion.
    close_kernel = np.ones((5, 5), np.uint8)
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, close_kernel, iterations=2)
    keep = _fill_enclosed_holes(keep, head_oval)

    # C/strong mode gets an additional constrained hull only in the upper-head
    # region.  It repairs broken hair masses while remaining bounded by the
    # anatomical oval, so cabinet/wall pixels cannot return as broad rectangles.
    if strong:
        contours, _ = cv2.findContours(
            (keep * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if contours:
            contour = max(contours, key=cv2.contourArea)
            hull = cv2.convexHull(contour)
            hull_mask = np.zeros_like(keep)
            cv2.fillConvexPoly(hull_mask, hull, 1)
            upper_limit = int(round((y + fh * 0.82) - y1))
            upper_limit = max(0, min(rh, upper_limit))
            upper_gate = np.zeros_like(keep)
            upper_gate[:upper_limit, :] = 1
            repair = hull_mask * upper_gate * head_oval.astype(np.uint8)
            keep = np.maximum(keep, repair)

    # Preserve a natural but continuous silhouette.  A 3x3 opening removes only
    # isolated single-pixel noise; it is intentionally not followed by erosion.
    small = np.ones((3, 3), np.uint8)
    keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, small, iterations=1)
    keep *= head_oval.astype(np.uint8)

    full = np.zeros((h, w), dtype=np.uint8)
    full[y1:y2, x1:x2] = (keep * 255).astype(np.uint8)
    out = Image.fromarray(full, "L")
    return out.filter(ImageFilter.GaussianBlur(0.55 if strong else 0.65))


def _clean_head_overlay(
    *, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
    target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
    baseline_full_raw: bytes, outer_strength: float, core_strength: float,
) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    source_img = fs.image(source_full_raw).convert("RGB")
    target_img = fs.image(target_full_raw).convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")

    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, twf, thf = [float(v) for v in target_face_box]
    if min(sw, sh, twf, thf) < 64:
        raise ValueError("face region is too small for V265 head alignment")

    strong = bool(outer_strength >= 0.85)
    W, H = target_img.size
    tl = max(0, int(round(tx - twf * 0.30)))
    tr = min(W, int(round(tx + twf * 1.30)))
    tt = max(0, int(round(ty - thf * 0.60)))
    tb = min(H, int(round(ty + thf * 1.18)))
    pw, ph = tr - tl, tb - tt
    if pw < 128 or ph < 180:
        raise ValueError("target V265 patch is too small")

    scale = 0.5 * ((sw / twf) + (sh / thf))
    c = sx + (float(tl) - tx) * scale
    f = sy + (float(tt) - ty) * scale
    affine_mode = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    resample_rgb = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    resample_mask = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source_img.transform(
        (pw, ph), affine_mode,
        (scale, 0.0, c, 0.0, scale, f),
        resample=resample_rgb, fillcolor=(0, 0, 0),
    )

    source_alpha = _foreground_mask(
        source_img,
        tuple(int(v) for v in source_face_box),
        strong=strong,
    )
    warped_alpha = source_alpha.transform(
        (pw, ph), affine_mode,
        (scale, 0.0, c, 0.0, scale, f),
        resample=resample_mask, fillcolor=0,
    )

    reference = baseline.crop((tl, tt, tr, tb))
    match_amount = 0.20 if not strong else 0.16
    warped = v262._color_match(warped, reference, amount=match_amount)

    lfx = tx - tl
    lfy = ty - tt

    gate = Image.new("L", (pw, ph), 0)
    gd = ImageDraw.Draw(gate)
    gx1 = max(0, int(round(lfx - twf * 0.24)))
    gy1 = max(0, int(round(lfy - thf * 0.52)))
    gx2 = min(pw, int(round(lfx + twf * 1.24)))
    gy2 = min(ph, int(round(lfy + thf * 1.08)))
    gd.ellipse((gx1, gy1, gx2, gy2), fill=255)

    ma = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ga = np.asarray(gate, dtype=np.float32) / 255.0
    ma *= ga

    tiny = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    edge_blur = 0.70 if not strong else 0.60
    tiny = tiny.filter(ImageFilter.GaussianBlur(edge_blur))
    ma = np.asarray(tiny, dtype=np.float32) / 255.0

    alpha_gain = 0.95 if not strong else 0.99
    ma *= alpha_gain

    # Keep the full source chin, then blend through a slightly longer neck band.
    # This reduces the abrupt adult-beard crescent immediately under the source jaw.
    jaw_start = min(ph, max(0, int(round(lfy + thf * 0.97))))
    fade_end = min(ph, max(jaw_start + 1, int(round(lfy + thf * 1.10))))
    if fade_end > jaw_start:
        ramp = np.linspace(1.0, 0.0, fade_end - jaw_start, dtype=np.float32)[:, None]
        ma[jaw_start:fade_end, :] *= ramp
    ma[fade_end:, :] = 0.0

    wa = np.asarray(warped, dtype=np.uint8)
    valid = (wa.max(axis=2) > 7).astype(np.float32)
    ma *= valid

    core = Image.new("L", (pw, ph), 0)
    cd = ImageDraw.Draw(core)
    cx1 = max(0, int(round(lfx + twf * 0.02)))
    cy1 = max(0, int(round(lfy - thf * 0.14)))
    cx2 = min(pw, int(round(lfx + twf * 0.98)))
    cy2 = min(ph, int(round(lfy + thf * 0.97)))
    cd.ellipse((cx1, cy1, cx2, cy2), fill=int(round(255 * min(1.0, max(0.0, core_strength)))))
    ca = np.asarray(core.filter(ImageFilter.GaussianBlur(0.9)), dtype=np.float32) / 255.0
    seg = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ma = np.maximum(ma, ca * seg)

    combined = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, combined)
    output = baseline.copy()
    output.paste(merged, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v265c_hole_filled_hair_silhouette",
        "target_patch": (tl, tt, tr, tb),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "gate_bounds": (gx1, gy1, gx2, gy2),
        "jaw_start": jaw_start,
        "fade_end": fade_end,
        "edge_blur": edge_blur,
        "alpha_gain": alpha_gain,
        "color_match": match_amount,
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "opencv_seeded_connected_holefill_hull" if strong else "opencv_seeded_connected_holefill",
    }


v262._full_head_overlay = _clean_head_overlay
media = v262.media


def install() -> bool:
    global _INSTALLED
    v262._full_head_overlay = _clean_head_overlay
    if _INSTALLED and getattr(diag.media, "_v265_clean_head_owned", False):
        return True
    setattr(media, "_v265_clean_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v265_clean_head_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
