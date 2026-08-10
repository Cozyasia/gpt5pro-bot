# -*- coding: utf-8 -*-
"""V264 affine-aligned head-ring integration diagnostic.

The V263 test proved that a smaller feather alone is not enough: resizing a huge
source head rectangle to a target rectangle can misalign the identity and carry
source background into the blend. V264 keeps the V261 InSwapper result as the
face core, aligns the source to the target by the detected face boxes, and only
lets source pixels influence a narrow anatomical ring around hairline/forehead/
temples. Lower jaw, neck, shoulders and source background are excluded.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v264-affine-head-ring-2026-08-10-r2"
_INSTALLED = False


def _seam_aware_overlay(
    *, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
    target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
    baseline_full_raw: bytes, outer_strength: float, core_strength: float,
    feather_ratio: float = 0.008,
) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    source_img = fs.image(source_full_raw).convert("RGB")
    target_img = fs.image(target_full_raw).convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")

    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, twf, thf = [float(v) for v in target_face_box]
    if sw < 64 or sh < 64 or twf < 64 or thf < 64:
        raise ValueError("face region is too small for V264 alignment")

    # Work only around the target head. These margins intentionally stay much
    # tighter than V262/V263 head_box so no shoulder or large background slab can
    # enter the compositor.
    W, H = target_img.size
    tl = max(0, int(round(tx - twf * 0.25)))
    tr = min(W, int(round(tx + twf * 1.25)))
    tt = max(0, int(round(ty - thf * 0.50)))
    tb = min(H, int(round(ty + thf * 1.02)))
    pw, ph = tr - tl, tb - tt
    if pw < 128 or ph < 160:
        raise ValueError("target V264 patch is too small")

    # Affine alignment by face boxes. Unlike the old head-box resize, this maps
    # source eyes/nose/hairline to the same face-normalized coordinates as target.
    scale_x = sw / twf
    scale_y = sh / thf
    c = sx + (float(tl) - tx) * scale_x
    f = sy + (float(tt) - ty) * scale_y
    affine_mode = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))

    # Pillow's affine transform only supports NEAREST/BILINEAR/BICUBIC. LANCZOS
    # is valid for resize(), but raises ValueError here. Use BICUBIC for the warp.
    affine_resample = (
        Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    )
    warped = source_img.transform(
        (pw, ph), affine_mode,
        (scale_x, 0.0, c, 0.0, scale_y, f),
        resample=affine_resample,
        fillcolor=(0, 0, 0),
    )
    reference = baseline.crop((tl, tt, tr, tb))
    warped = v262._color_match(warped, reference, amount=0.34)

    # Target face coordinates inside the patch.
    lfx = tx - tl
    lfy = ty - tt

    # Outer anatomical head/hair region. It reaches above the hairline and around
    # temples, but stops before the lower jaw/neck. This is intentionally not a
    # full-head ellipse: the previous broad ellipse produced the visible ghost.
    outer = Image.new("L", (pw, ph), 0)
    od = ImageDraw.Draw(outer)
    ox1 = max(0, int(round(lfx - twf * 0.17)))
    oy1 = max(0, int(round(lfy - thf * 0.47)))
    ox2 = min(pw, int(round(lfx + twf * 1.17)))
    oy2 = min(ph, int(round(lfy + thf * 0.88)))
    od.ellipse((ox1, oy1, ox2, oy2), fill=int(round(255 * max(0.0, min(1.0, outer_strength)))))

    # Protect the V261/InSwapper face core. Source authority is a ring around the
    # face, not a second overwrite of eyes/nose/mouth. Stronger core_strength means
    # stronger protection of the provider face.
    protect = Image.new("L", (pw, ph), 0)
    pd = ImageDraw.Draw(protect)
    px1 = max(0, int(round(lfx + twf * 0.015)))
    py1 = max(0, int(round(lfy + thf * 0.055)))
    px2 = min(pw, int(round(lfx + twf * 0.985)))
    py2 = min(ph, int(round(lfy + thf * 0.92)))
    pd.ellipse((px1, py1, px2, py2), fill=int(round(255 * max(0.0, min(1.0, core_strength)))))

    # Tight feather. Keep the ring crisp enough to avoid a cloudy halo while still
    # hiding single-pixel seams along hair and temple boundaries.
    feather = max(2, int(round(min(pw, ph) * feather_ratio)))
    outer = outer.filter(ImageFilter.GaussianBlur(feather))
    protect = protect.filter(ImageFilter.GaussianBlur(max(2, feather - 1)))
    ma = np.asarray(outer, dtype=np.float32)
    pa = np.asarray(protect, dtype=np.float32) / 255.0
    ma *= (1.0 - pa)

    # Hard spatial gate below the lower cheek. This eliminates the V262/V263 neck
    # and shoulder ghost even if the outer ellipse or blur would otherwise leak.
    cutoff = min(ph, int(round(lfy + thf * 0.82)))
    fade_end = min(ph, cutoff + max(3, int(round(thf * 0.045))))
    if fade_end > cutoff:
        ramp = np.linspace(1.0, 0.0, fade_end - cutoff, dtype=np.float32)[:, None]
        ma[cutoff:fade_end, :] *= ramp
    ma[fade_end:, :] = 0.0

    # Reject transform fill pixels entirely. They are pure black only when affine
    # sampling runs outside the source image; never allow them into the composite.
    wa = np.asarray(warped, dtype=np.uint8)
    valid = (wa.max(axis=2) > 8).astype(np.float32)
    ma *= valid

    combined = Image.fromarray(np.clip(ma, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, combined)
    output = baseline.copy()
    output.paste(merged, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v264_affine_head_ring",
        "target_patch": (tl, tt, tr, tb),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale_x": round(scale_x, 4), "scale_y": round(scale_y, 4),
        "ring_bounds": (ox1, oy1, ox2, oy2),
        "core_bounds": (px1, py1, px2, py2),
        "cutoff": cutoff, "fade_end": fade_end, "feather": feather,
        "outer_strength": float(outer_strength), "core_protection": float(core_strength),
    }


# Reuse V262 session/provider/A-B-C delivery machinery, but replace only the
# compositor. This keeps the diagnostic isolated from production AI Selfie.
v262._full_head_overlay = _seam_aware_overlay
media = v262.media


def install() -> bool:
    """Make the V264 compositor the actual Face Swap diagnostic callback owner."""
    global _INSTALLED
    v262._full_head_overlay = _seam_aware_overlay
    if _INSTALLED and getattr(diag.media, "_v264_affine_head_ring_owned", False):
        return True
    setattr(media, "_v264_affine_head_ring_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v264_affine_head_ring_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
