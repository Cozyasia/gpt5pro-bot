# -*- coding: utf-8 -*-
"""V265 clean segmented head-transplant diagnostic.

Goal: keep the successful V262/V263 direction where the source identity controls
THE WHOLE HEAD, but remove the cloudy halo / crescent / source-background ghost.

Instead of painting a broad geometric ellipse from the source image, V265:
1) aligns the source to the target by the detected face boxes;
2) obtains a foreground alpha matte for the source person (rembg/u2netp);
3) intersects that matte with a tight anatomical head gate;
4) keeps hair/ear edges from the segmentation matte almost crisp;
5) fades only the lower jaw/upper-neck transition into the adult target body.

The isolated Face Swap test still returns A/B/C. Production AI-selfie is not
changed by this module.
"""
from __future__ import annotations

import contextlib
import threading
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v265-clean-segmented-head-transplant-2026-08-11"
_INSTALLED = False
_REMBG_SESSION: Any | None = None
_REMBG_LOCK = threading.Lock()


def _foreground_mask(source_img: Any) -> Any:
    """Return an 8-bit person matte; cache the small u2netp session.

    If rembg cannot initialise, fail explicitly rather than silently returning to
    the old broad ellipse, because that old fallback is exactly what produced the
    visible halo we are trying to remove.
    """
    global _REMBG_SESSION
    from PIL import Image
    from rembg import new_session, remove

    with _REMBG_LOCK:
        if _REMBG_SESSION is None:
            _REMBG_SESSION = new_session("u2netp")
        session = _REMBG_SESSION

    mask = remove(source_img.convert("RGB"), session=session, only_mask=True)
    if not isinstance(mask, Image.Image):
        mask = Image.open(mask)
    return mask.convert("L")


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

    # Tight patch around the target head. It intentionally ends shortly below
    # the chin; shoulders and chest never enter the source-authority region.
    tl = max(0, int(round(tx - twf * 0.34)))
    tr = min(W, int(round(tx + twf * 1.34)))
    tt = max(0, int(round(ty - thf * 0.63)))
    tb = min(H, int(round(ty + thf * 1.20)))
    pw, ph = tr - tl, tb - tt
    if pw < 128 or ph < 180:
        raise ValueError("target V265 patch is too small")

    # Face-normalised affine mapping. Use one uniform scale so head proportions
    # are not stretched independently in X/Y.
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

    # Crucial difference from V262/V264: alpha follows the actual source person
    # silhouette, especially hair and ears, instead of a blurred ellipse.
    source_alpha = _foreground_mask(source_img)
    warped_alpha = source_alpha.transform(
        (pw, ph), affine_mode,
        (scale, 0.0, c, 0.0, scale, f),
        resample=resample_mask, fillcolor=0,
    )

    reference = baseline.crop((tl, tt, tr, tb))
    # Small lighting adaptation only; high identity fidelity is more important
    # than forcing the source skin/hair to inherit all target statistics.
    match_amount = 0.16 if outer_strength < 0.85 else 0.10
    warped = v262._color_match(warped, reference, amount=match_amount)

    lfx = tx - tl
    lfy = ty - tt

    # Anatomical head gate: large enough for hair/ears, but explicitly not a
    # shoulder/body ellipse. Segmentation supplies the actual silhouette inside.
    gate = Image.new("L", (pw, ph), 0)
    gd = ImageDraw.Draw(gate)
    gx1 = max(0, int(round(lfx - twf * 0.30)))
    gy1 = max(0, int(round(lfy - thf * 0.58)))
    gx2 = min(pw, int(round(lfx + twf * 1.30)))
    gy2 = min(ph, int(round(lfy + thf * 1.12)))
    gd.ellipse((gx1, gy1, gx2, gy2), fill=255)

    ma = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ga = np.asarray(gate, dtype=np.float32) / 255.0
    ma *= ga

    # Do NOT broadly feather the whole head. Preserve the hair segmentation edge
    # and apply only a tiny anti-aliasing blur (roughly 1 px at this resolution).
    tiny = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    tiny = tiny.filter(ImageFilter.GaussianBlur(0.75))
    ma = np.asarray(tiny, dtype=np.float32) / 255.0

    # Local strength. B is slightly more forgiving at the perimeter; C is close
    # to a literal source-head transplant.
    alpha_gain = 0.94 if outer_strength < 0.85 else 1.0
    ma *= alpha_gain

    # Lower seam control: preserve the source jaw/chin, then fade only through a
    # short upper-neck strip. Everything below returns to the adult target body.
    jaw_start = min(ph, max(0, int(round(lfy + thf * 0.96))))
    fade_end = min(ph, max(jaw_start + 1, int(round(lfy + thf * 1.13))))
    if fade_end > jaw_start:
        ramp = np.linspace(1.0, 0.0, fade_end - jaw_start, dtype=np.float32)[:, None]
        ma[jaw_start:fade_end, :] *= ramp
    ma[fade_end:, :] = 0.0

    # Reject affine fill pixels. This also prevents accidental dark wedges around
    # the transformed crop if sampling reaches outside the source photograph.
    wa = np.asarray(warped, dtype=np.uint8)
    valid = (wa.max(axis=2) > 7).astype(np.float32)
    ma *= valid

    # Make the central identity literal. This avoids the hybrid look while still
    # letting the segmented perimeter and neck fade do the integration work.
    core = Image.new("L", (pw, ph), 0)
    cd = ImageDraw.Draw(core)
    cx1 = max(0, int(round(lfx - twf * 0.05)))
    cy1 = max(0, int(round(lfy - thf * 0.20)))
    cx2 = min(pw, int(round(lfx + twf * 1.05)))
    cy2 = min(ph, int(round(lfy + thf * 1.00)))
    cd.ellipse((cx1, cy1, cx2, cy2), fill=int(round(255 * min(1.0, max(0.0, core_strength)))))
    ca = np.asarray(core.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255.0
    # Core cannot invent pixels outside the segmented person matte.
    seg = np.asarray(warped_alpha, dtype=np.float32) / 255.0
    ma = np.maximum(ma, ca * seg)

    combined = Image.fromarray(np.clip(ma * 255.0, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, combined)
    output = baseline.copy()
    output.paste(merged, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v265_clean_segmented_head_transplant",
        "target_patch": (tl, tt, tr, tb),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "gate_bounds": (gx1, gy1, gx2, gy2),
        "jaw_start": jaw_start,
        "fade_end": fade_end,
        "edge_blur": 0.75,
        "alpha_gain": alpha_gain,
        "color_match": match_amount,
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
    }


# Reuse V262 session/provider/A-B-C delivery machinery, replace only B/C head
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
