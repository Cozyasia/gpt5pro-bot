# -*- coding: utf-8 -*-
"""V265 lightweight clean head-transplant diagnostic.

Goal: preserve the successful V262/V263 full-head identity direction while
removing the cloudy halo / crescent / source-background ghost without loading
rembg/U2NET/ONNX into the Telegram bot process.

This revision keeps the low-memory OpenCV path but fixes the main failure seen
in the 3803b016288f test: the detector face *rectangle* was previously marked as
certain foreground, so background pixels in the rectangle corners (cabinet/wall)
could be transplanted together with the head. We now use an anatomical elliptical
seed, a tighter probable-head gate, and retain only foreground connected to the
face seed.

The isolated Face Swap test still returns A/B/C. Production AI-selfie is not
changed by this module.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v265b-seeded-connected-head-mask-2026-08-12"
_INSTALLED = False


def _foreground_mask(source_img: Any, source_face_box: tuple[int, int, int, int]) -> Any:
    """Return a low-memory 8-bit head matte using seeded GrabCut + connectivity.

    Important: never mark the whole detector rectangle as certain foreground.
    Detector boxes contain background in their corners, which is exactly what
    produced the rectangular/crescent source-background artifacts in V265.
    """
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    rgb = np.asarray(source_img.convert("RGB"), dtype=np.uint8)
    h, w = rgb.shape[:2]
    x, y, fw, fh = [int(v) for v in source_face_box]

    # Head-local working window. It is intentionally smaller than the previous
    # V265 window so shoulders and large source-background regions never become
    # candidates for the matte.
    x1 = max(0, int(round(x - fw * 0.30)))
    y1 = max(0, int(round(y - fh * 0.62)))
    x2 = min(w, int(round(x + fw * 1.30)))
    y2 = min(h, int(round(y + fh * 1.16)))
    rw, rh = x2 - x1, y2 - y1
    if rw < 64 or rh < 80:
        raise ValueError("source head region is too small for OpenCV mask")

    crop = cv2.cvtColor(rgb[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
    mask = np.full((rh, rw), cv2.GC_BGD, dtype=np.uint8)
    yy, xx = np.ogrid[:rh, :rw]

    # Probable head/hair region. Tighter than V265: enough for hairstyle and
    # ears, but not enough to swallow a cabinet/wall around the head.
    cx = (x + fw * 0.50) - x1
    cy = (y + fh * 0.40) - y1
    rx = max(8.0, fw * 0.72)
    ry = max(10.0, fh * 0.98)
    head_oval = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    mask[head_oval] = cv2.GC_PR_FGD

    # Certain foreground is an INNER FACE ELLIPSE, not the rectangular detector
    # box. This is the key artifact fix: rectangle corners remain background.
    fcx = (x + fw * 0.50) - x1
    fcy = (y + fh * 0.54) - y1
    frx = max(6.0, fw * 0.40)
    fry = max(8.0, fh * 0.46)
    face_seed = ((xx - fcx) / frx) ** 2 + ((yy - fcy) / fry) ** 2 <= 1.0
    mask[face_seed] = cv2.GC_FGD

    # A smaller central skin seed makes the component selection deterministic.
    srx = max(4.0, fw * 0.22)
    sry = max(5.0, fh * 0.25)
    center_seed = ((xx - fcx) / srx) ** 2 + ((yy - fcy) / sry) ** 2 <= 1.0

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(crop, mask, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
        fg = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
    except cv2.error:
        # Deterministic low-memory fallback. Still use the tight head oval and
        # never return a broad source-background rectangle.
        fg = np.where(head_oval, 255, 0).astype(np.uint8)

    # Reject disconnected foreground. Keep only components touching the central
    # face seed; this removes cabinets, wall patches and other source scenery even
    # when GrabCut classifies them as probable foreground.
    binary = (fg > 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    keep = np.zeros_like(binary)
    seed_labels = np.unique(labels[center_seed])
    seed_labels = [int(v) for v in seed_labels if int(v) != 0]
    if seed_labels:
        for lab in seed_labels:
            keep[labels == lab] = 1
    elif n > 1:
        # Fallback: retain the largest non-background component.
        lab = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        keep[labels == lab] = 1
    else:
        keep = binary

    # Hard anatomical guard. Connectivity alone is not enough if background is
    # touching hair in the source image.
    keep = keep * head_oval.astype(np.uint8)

    # Repair tiny gaps in hair, then slightly contract once to avoid a dark/bright
    # fringe from the source background. We do not broadly blur the mask.
    kernel = np.ones((3, 3), np.uint8)
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, kernel, iterations=2)
    keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, kernel, iterations=1)
    keep = cv2.erode(keep, kernel, iterations=1)
    fg = (keep * 255).astype(np.uint8)

    full = np.zeros((h, w), dtype=np.uint8)
    full[y1:y2, x1:x2] = fg
    out = Image.fromarray(full, "L")
    # Sub-pixel anti-aliasing only. No cloudy halo.
    return out.filter(ImageFilter.GaussianBlur(0.45))


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

    W, H = target_img.size
    tl = max(0, int(round(tx - twf * 0.30)))
    tr = min(W, int(round(tx + twf * 1.30)))
    tt = max(0, int(round(ty - thf * 0.58)))
    tb = min(H, int(round(ty + thf * 1.16)))
    pw, ph = tr - tl, tb - tt
    if pw < 128 or ph < 180:
        raise ValueError("target V265 patch is too small")

    # Uniform face-normalised mapping; independent X/Y stretching is avoided.
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

    source_alpha = _foreground_mask(source_img, tuple(int(v) for v in source_face_box))
    warped_alpha = source_alpha.transform(
        (pw, ph), affine_mode,
        (scale, 0.0, c, 0.0, scale, f),
        resample=resample_mask, fillcolor=0,
    )

    reference = baseline.crop((tl, tt, tr, tb))
    match_amount = 0.18 if outer_strength < 0.85 else 0.14
    warped = v262._color_match(warped, reference, amount=match_amount)

    lfx = tx - tl
    lfy = ty - tt

    # Tight target anatomical gate. This is a second independent guard against
    # any source-background pixel escaping the segmentation.
    gate = Image.new("L", (pw, ph), 0)
    gd = ImageDraw.Draw(gate)
    gx1 = max(0, int(round(lfx - twf * 0.24)))
    gy1 = max(0, int(round(lfy - thf * 0.50)))
    gx2 = min(pw, int(round(lfx + twf * 1.24)))
    gy2 = min(ph, int(round(lfy + thf * 1.06)))
    gd.ellipse((gx1, gy1, gx2, gy2), fill=255)

    ma = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ga = np.asarray(gate, dtype=np.float32) / 255.0
    ma *= ga

    tiny = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    tiny = tiny.filter(ImageFilter.GaussianBlur(0.45))
    ma = np.asarray(tiny, dtype=np.float32) / 255.0

    alpha_gain = 0.94 if outer_strength < 0.85 else 0.98
    ma *= alpha_gain

    # Preserve chin, then dissolve only through a short upper-neck strip.
    jaw_start = min(ph, max(0, int(round(lfy + thf * 0.92))))
    fade_end = min(ph, max(jaw_start + 1, int(round(lfy + thf * 1.05))))
    if fade_end > jaw_start:
        ramp = np.linspace(1.0, 0.0, fade_end - jaw_start, dtype=np.float32)[:, None]
        ma[jaw_start:fade_end, :] *= ramp
    ma[fade_end:, :] = 0.0

    # Reject affine fill pixels.
    wa = np.asarray(warped, dtype=np.uint8)
    valid = (wa.max(axis=2) > 7).astype(np.float32)
    ma *= valid

    # Strong identity core, but strictly inside segmented source foreground.
    core = Image.new("L", (pw, ph), 0)
    cd = ImageDraw.Draw(core)
    cx1 = max(0, int(round(lfx + twf * 0.02)))
    cy1 = max(0, int(round(lfy - thf * 0.12)))
    cx2 = min(pw, int(round(lfx + twf * 0.98)))
    cy2 = min(ph, int(round(lfy + thf * 0.94)))
    cd.ellipse((cx1, cy1, cx2, cy2), fill=int(round(255 * min(1.0, max(0.0, core_strength)))))
    ca = np.asarray(core.filter(ImageFilter.GaussianBlur(0.8)), dtype=np.float32) / 255.0
    seg = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ma = np.maximum(ma, ca * seg)

    combined = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, combined)
    output = baseline.copy()
    output.paste(merged, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v265b_seeded_connected_head_mask",
        "target_patch": (tl, tt, tr, tb),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "gate_bounds": (gx1, gy1, gx2, gy2),
        "jaw_start": jaw_start,
        "fade_end": fade_end,
        "edge_blur": 0.45,
        "alpha_gain": alpha_gain,
        "color_match": match_amount,
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "opencv_grabcut_seeded_connected_component",
    }


# Reuse V262 session/provider/A-B-C delivery machinery, replacing only B/C head
# integration. A remains the InSwapper control image.
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
