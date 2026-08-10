# -*- coding: utf-8 -*-
"""V263 seam-aware head integration diagnostic.

Fixes the visible V262 halo/seam by keeping V261 InSwapper as the identity core
and restricting source-head authority to an anatomical upper-head region.
No source neck/shoulders/background are allowed into the composite.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v263-seam-aware-head-integration-2026-08-10-r2"
_INSTALLED = False


def _seam_aware_overlay(
    *, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
    target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
    baseline_full_raw: bytes, outer_strength: float, core_strength: float,
    feather_ratio: float = 0.012,
) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    source_img = fs.image(source_full_raw)
    target_img = fs.image(target_full_raw)
    baseline = fs.image(baseline_full_raw)
    source_box = v262._head_box(source_face_box, source_img.size)
    target_box = v262._head_box(target_face_box, target_img.size)
    sl, st, sr, sb = source_box
    tl, tt, tr, tb = target_box
    tw, th = tr - tl, tb - tt
    if tw < 128 or th < 160:
        raise ValueError("target head region is too small")

    source_head = source_img.crop(source_box).resize((tw, th), Image.LANCZOS)
    reference = baseline.crop(target_box)
    source_head = v262._color_match(source_head, reference, amount=0.58)

    # Anatomical upper-head mask. Deliberately terminates above lower neck and
    # never reaches shoulders/corners, which caused V262's broad ghost halo.
    fx, fy, fw, fh = target_face_box
    lfx, lfy = fx - tl, fy - tt
    head_left = max(0, int(lfx - fw * 0.24))
    head_right = min(tw, int(lfx + fw * 1.24))
    head_top = max(0, int(lfy - fh * 0.54))
    head_bottom = min(th, int(lfy + fh * 1.02))

    mask = Image.new("L", (tw, th), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((head_left, head_top, head_right, head_bottom), fill=int(255 * outer_strength))

    # Hard exclusion below jaw: fade source authority to zero before the neck.
    jaw_y = min(th - 1, int(lfy + fh * 0.96))
    fade_end = min(th, jaw_y + max(3, int(fh * 0.08)))
    ma = np.asarray(mask, dtype=np.float32)
    if fade_end > jaw_y:
        ramp = np.linspace(1.0, 0.0, fade_end - jaw_y, dtype=np.float32)[:, None]
        ma[jaw_y:fade_end, :] *= ramp
    ma[fade_end:, :] = 0.0
    mask = Image.fromarray(np.clip(ma, 0, 255).astype(np.uint8), "L")

    # Much tighter transition than V262.
    feather = max(2, int(min(tw, th) * feather_ratio))
    mask = mask.filter(ImageFilter.GaussianBlur(feather))

    # Preserve the already-clean V261/InSwapper face as the core. Source pixels
    # are primarily for hairline/forehead/temples/head silhouette, not a second
    # raw overwrite of eyes/nose/mouth.
    protect = Image.new("L", (tw, th), 0)
    pd = ImageDraw.Draw(protect)
    px1 = max(0, int(lfx - fw * 0.02)); py1 = max(0, int(lfy - fh * 0.02))
    px2 = min(tw, int(lfx + fw * 1.02)); py2 = min(th, int(lfy + fh * 1.00))
    pd.ellipse((px1, py1, px2, py2), fill=int(255 * core_strength))
    protect = protect.filter(ImageFilter.GaussianBlur(max(2, int(min(fw, fh) * 0.018))))
    m = np.asarray(mask, dtype=np.float32)
    p = np.asarray(protect, dtype=np.float32) / 255.0
    m *= (1.0 - p)
    combined = Image.fromarray(np.clip(m, 0, 255).astype(np.uint8), "L")

    merged = Image.composite(source_head, reference, combined)
    output = baseline.copy()
    output.paste(merged, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)
    return payload, {
        "source_head_box": source_box, "target_head_box": target_box,
        "head_bounds": (head_left, head_top, head_right, head_bottom),
        "jaw_y": jaw_y, "fade_end": fade_end, "feather": feather,
        "outer_strength": outer_strength, "core_protection": core_strength,
    }


# Reuse V262 transport/session/provider machinery; only replace its full-head
# compositor. V262 media resolves this module-global function at runtime.
v262._full_head_overlay = _seam_aware_overlay
media = v262.media


def install() -> bool:
    """Make V263 the actual callback owner before Telegram binds handlers."""
    global _INSTALLED
    v262._full_head_overlay = _seam_aware_overlay
    if _INSTALLED and getattr(diag.media, "_v263_seam_aware_owned", False):
        return True
    setattr(media, "_v263_seam_aware_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v263_seam_aware_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
