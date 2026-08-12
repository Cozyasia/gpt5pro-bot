# -*- coding: utf-8 -*-
"""V265 lightweight clean head-transplant diagnostic.

Goal: preserve the successful V262/V263 full-head identity direction while
removing the cloudy halo / crescent / source-background ghost without loading
rembg/U2NET/ONNX into the Telegram bot process.

V265 now uses only Pillow + NumPy + OpenCV, which are already part of the bot:
1) align source to target by detected face boxes;
2) build a lightweight source-head matte with OpenCV GrabCut around the face;
3) intersect that matte with a tight anatomical head gate;
4) keep hair/ear edges comparatively crisp;
5) fade only the lower jaw/upper-neck transition into the target body.

The isolated Face Swap test still returns A/B/C. Production AI-selfie is not
changed by this module.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v265-lightweight-opencv-head-transplant-2026-08-12"
_INSTALLED = False


def _foreground_mask(source_img: Any, source_face_box: tuple[int, int, int, int]) -> Any:
    """Return a lightweight 8-bit head/person matte using OpenCV GrabCut.

    The segmentation is deliberately local to the head region. It avoids any
    neural-network runtime and therefore avoids the large RAM spike that caused
    Render OOM restarts when rembg/U2NET was imported.
    """
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    rgb = np.asarray(source_img.convert("RGB"), dtype=np.uint8)
    h, w = rgb.shape[:2]
    x, y, fw, fh = [int(v) for v in source_face_box]

    # Tight source-head working rectangle: enough room for hair/ears, but not
    # shoulders/chest. Clamp aggressively to the image bounds.
    x1 = max(0, int(round(x - fw * 0.42)))
    y1 = max(0, int(round(y - fh * 0.78)))
    x2 = min(w, int(round(x + fw * 1.42)))
    y2 = min(h, int(round(y + fh * 1.28)))
    rw, rh = x2 - x1, y2 - y1
    if rw < 64 or rh < 80:
        raise ValueError("source head region is too small for OpenCV mask")

    crop = cv2.cvtColor(rgb[y1:y2, x1:x2], cv2.COLOR_RGB2BGR)
    mask = np.full((rh, rw), cv2.GC_BGD, dtype=np.uint8)

    # Probable foreground occupies the central head oval.
    yy, xx = np.ogrid[:rh, :rw]
    cx = (x + fw * 0.50) - x1
    cy = (y + fh * 0.34) - y1
    rx = max(8.0, fw * 0.88)
    ry = max(10.0, fh * 1.18)
    head_oval = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    mask[head_oval] = cv2.GC_PR_FGD

    # The detected face itself is certain foreground. This anchors GrabCut so
    # skin/eyes/nose/mouth cannot be discarded by the background model.
    fx1 = max(0, x - x1)
    fy1 = max(0, y - y1)
    fx2 = min(rw, x + fw - x1)
    fy2 = min(rh, y + fh - y1)
    if fx2 > fx1 and fy2 > fy1:
        mask[fy1:fy2, fx1:fx2] = cv2.GC_FGD

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(crop, mask, None, bgd, fgd, 3, cv2.GC_INIT_WITH_MASK)
        fg = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
    except cv2.error:
        # Deterministic low-memory fallback: anatomical oval, never the old broad
        # full-head ellipse that leaked source background into the target.
        fg = np.where(head_oval, 255, 0).astype(np.uint8)

    # Remove small speckles and close tiny gaps in hair. Kernels remain small so
    # the matte does not grow into a visible halo.
    kernel = np.ones((3, 3), np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)

    full = np.zeros((h, w), dtype=np.uint8)
    full[y1:y2, x1:x2] = fg
    out = Image.fromarray(full, "L")
    return out.filter(ImageFilter.GaussianBlur(0.85))


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
    tl = max(0, int(round(tx - twf * 0.34)))
    tr = min(W, int(round(tx + twf * 1.34)))
    tt = max(0, int(round(ty - thf * 0.63)))
    tb = min(H, int(round(ty + thf * 1.20)))
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
    match_amount = 0.14 if outer_strength < 0.85 else 0.09
    warped = v262._color_match(warped, reference, amount=match_amount)

    lfx = tx - tl
    lfy = ty - tt

    # Anatomical gate restricts the segmentation to the actual head zone.
    gate = Image.new("L", (pw, ph), 0)
    gd = ImageDraw.Draw(gate)
    gx1 = max(0, int(round(lfx - twf * 0.30)))
    gy1 = max(0, int(round(lfy - thf * 0.58)))
    gx2 = min(pw, int(round(lfx + twf * 1.30)))
    gy2 = min(ph, int(round(lfy + thf * 1.10)))
    gd.ellipse((gx1, gy1, gx2, gy2), fill=255)

    ma = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ga = np.asarray(gate, dtype=np.float32) / 255.0
    ma *= ga

    # Keep perimeter sharper than V262/V264. A tiny blur is only anti-aliasing.
    tiny = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    tiny = tiny.filter(ImageFilter.GaussianBlur(0.65))
    ma = np.asarray(tiny, dtype=np.float32) / 255.0

    alpha_gain = 0.95 if outer_strength < 0.85 else 1.0
    ma *= alpha_gain

    # Preserve chin, then perform a short vertical dissolve into the target neck.
    jaw_start = min(ph, max(0, int(round(lfy + thf * 0.94))))
    fade_end = min(ph, max(jaw_start + 1, int(round(lfy + thf * 1.10))))
    if fade_end > jaw_start:
        ramp = np.linspace(1.0, 0.0, fade_end - jaw_start, dtype=np.float32)[:, None]
        ma[jaw_start:fade_end, :] *= ramp
    ma[fade_end:, :] = 0.0

    # Reject affine fill pixels, preventing dark/transparent wedges.
    wa = np.asarray(warped, dtype=np.uint8)
    valid = (wa.max(axis=2) > 7).astype(np.float32)
    ma *= valid

    # Strong identity core, but never outside the OpenCV foreground matte.
    core = Image.new("L", (pw, ph), 0)
    cd = ImageDraw.Draw(core)
    cx1 = max(0, int(round(lfx - twf * 0.04)))
    cy1 = max(0, int(round(lfy - thf * 0.18)))
    cx2 = min(pw, int(round(lfx + twf * 1.04)))
    cy2 = min(ph, int(round(lfy + thf * 0.99)))
    cd.ellipse((cx1, cy1, cx2, cy2), fill=int(round(255 * min(1.0, max(0.0, core_strength)))))
    ca = np.asarray(core.filter(ImageFilter.GaussianBlur(1.0)), dtype=np.float32) / 255.0
    seg = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ma = np.maximum(ma, ca * seg)

    combined = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, combined)
    output = baseline.copy()
    output.paste(merged, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v265_lightweight_opencv_head_transplant",
        "target_patch": (tl, tt, tr, tb),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "gate_bounds": (gx1, gy1, gx2, gy2),
        "jaw_start": jaw_start,
        "fade_end": fade_end,
        "edge_blur": 0.65,
        "alpha_gain": alpha_gain,
        "color_match": match_amount,
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "opencv_grabcut",
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
