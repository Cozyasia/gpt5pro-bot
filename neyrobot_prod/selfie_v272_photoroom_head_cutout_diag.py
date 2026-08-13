# -*- coding: utf-8 -*-
"""V274 hybrid PhotoRoom-hair + InSwapper-face compositor.

V272/V273 proved that PhotoRoom gives a much better real foreground silhouette,
but pasting the complete source head still produced a sticker: source jaw/cheeks/
neck competed with the already well integrated InSwapper face.

V274 changes ownership instead of adding more feathering:
* InSwapper baseline owns the complete face, skin, jaw, ears and neck.
* PhotoRoom is used only to recover the source hair/crown/temple silhouette.
* The lower hairline is handed back to the InSwapper baseline through a soft,
  curved anatomical gate. There is no full-head paste and no neck seam.

This module patches only the isolated Face Swap diagnostic.
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v274-photoroom-hair-inswapper-face-blend-2026-08-13"
_INSTALLED = False


def _photoroom_rgba(source_raw: bytes):
    """Return PhotoRoom RGBA cutout. No synthetic segmentation fallback."""
    import httpx
    from PIL import Image

    key = (os.environ.get("PHOTOROOM_API_KEY") or os.environ.get("PHOTO_ROOM_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("PHOTOROOM_API_KEY is not configured")
    endpoint = (os.environ.get("PHOTOROOM_SEGMENT_URL") or "https://sdk.photoroom.com/v1/segment").strip()
    headers = {"x-api-key": key, "Accept": "image/png"}
    files = {"image_file": ("source.jpg", source_raw, "image/jpeg")}
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        response = client.post(endpoint, headers=headers, files=files)
        response.raise_for_status()
    im = Image.open(BytesIO(response.content)).convert("RGBA")
    if im.getbbox() is None:
        raise RuntimeError("PhotoRoom returned an empty cutout")
    return im


def _hair_alpha_from_rgba(rgba, face_box: tuple[int, int, int, int], *, strong: bool):
    """Build a PhotoRoom-owned alpha for hair/crown only, never a full head.

    PhotoRoom owns foreground/background classification. Geometry only decides
    which *part of that foreground* is allowed to replace the InSwapper baseline.
    The centre fades out around the upper forehead while the sides continue a bit
    lower to retain temples/side hair. Eyes, cheeks, jaw and neck are always zero.
    """
    import cv2
    import numpy as np
    from PIL import Image

    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    h, w = alpha.shape
    x, y, fw, fh = [float(v) for v in face_box]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # Limit PhotoRoom foreground to a generous head-width corridor. This removes
    # shoulders/body while leaving real flyaway hair and crown silhouette intact.
    cx = x + fw * 0.50
    half_w = fw * (0.76 if strong else 0.72)
    horizontal = np.clip((half_w - np.abs(xx - cx)) / max(fw * 0.055, 1.0), 0.0, 1.0)

    # Curved lower ownership boundary. The central forehead is handed to the
    # InSwapper baseline earlier; the sides retain a little more source hair.
    nx = np.clip(np.abs((xx - cx) / max(fw * 0.50, 1.0)), 0.0, 1.35)
    side_bonus = np.clip((nx - 0.35) / 0.75, 0.0, 1.0)
    cutoff = y + fh * ((0.105 if strong else 0.085) + (0.155 if strong else 0.135) * side_bonus)
    fade = max(10.0, fh * (0.095 if strong else 0.115))
    lower_gate = np.clip((cutoff + fade - yy) / fade, 0.0, 1.0)

    # Hard safety: source pixels must never own the lower face/jaw/neck.
    safety_bottom = y + fh * 0.34
    safety = np.clip((safety_bottom - yy) / max(fh * 0.035, 1.0), 0.0, 1.0)

    af = (alpha.astype(np.float32) / 255.0) * horizontal * lower_gate * safety

    # Keep only the connected PhotoRoom foreground component overlapping the
    # source head corridor. This rejects stray foreground islands in the crop.
    binary = (af >= 0.035).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count > 1:
        probe_y0 = max(0, int(round(y - fh * 0.70)))
        probe_y1 = min(h, int(round(y + fh * 0.16)))
        probe_x0 = max(0, int(round(x - fw * 0.30)))
        probe_x1 = min(w, int(round(x + fw * 1.30)))
        probe = labels[probe_y0:probe_y1, probe_x0:probe_x1]
        ids, freq = np.unique(probe[probe > 0], return_counts=True)
        if len(ids):
            chosen = int(ids[int(np.argmax(freq))])
            af = np.where(labels == chosen, af, 0.0).astype(np.float32)

    # Decontaminate PhotoRoom contour by shrinking only the opaque interior a
    # fraction, then rebuild a soft edge. This prevents bright background halos.
    opaque = (af >= 0.58).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    core = cv2.erode(opaque, kernel, iterations=1)
    edge = np.clip(af - core.astype(np.float32), 0.0, 1.0)
    sigma = max(1.0, fw * (0.0055 if strong else 0.0070))
    edge = cv2.GaussianBlur(edge, (0, 0), sigma)
    final = np.maximum(core.astype(np.float32), edge)

    # Hair interior remains opaque; only the real silhouette and lower handoff
    # are feathered. This avoids the translucent double-hair/ghosting effect.
    final[final >= 0.92] = 1.0
    return Image.fromarray(np.clip(final * 255.0, 0, 255).astype(np.uint8), "L")


def _harmonize_hair(warped, reference, alpha, *, strong: bool):
    """Match broad target lighting on hair without blurring source texture."""
    import cv2
    import numpy as np
    from PIL import Image

    src = np.asarray(warped.convert("RGB"), dtype=np.float32)
    ref = np.asarray(reference.convert("RGB"), dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32) / 255.0

    sigma = max(7.0, min(src.shape[0], src.shape[1]) * 0.025)
    src_low = cv2.GaussianBlur(src, (0, 0), sigma)
    ref_low = cv2.GaussianBlur(ref, (0, 0), sigma)
    delta = np.clip(ref_low - src_low, -28.0, 28.0)
    amount = 0.15 if strong else 0.22
    out = src + delta * amount

    # Only the transition band gets a little target-colour decontamination.
    band = np.clip(4.0 * a * (1.0 - a), 0.0, 1.0)[..., None]
    mix = 0.10 if strong else 0.15
    out = out * (1.0 - band * mix) + ref * (band * mix)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    """Overlay only source hair onto the already integrated InSwapper baseline."""
    from PIL import Image

    source_rgba = _photoroom_rgba(source_full_raw)
    source_rgb = source_rgba.convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")

    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    strong = bool(outer_strength >= 0.85)
    W, H = baseline.size

    # Hair-only work patch. It deliberately ends around the upper half of the
    # target face; nothing near jaw/neck can be pasted by this compositor.
    l = max(0, int(round(tx - tw * 0.72)))
    r = min(W, int(round(tx + tw * 1.72)))
    t = max(0, int(round(ty - th * 1.10)))
    b = min(H, int(round(ty + th * 0.46)))
    pw, ph = r - l, b - t
    if pw < 32 or ph < 32:
        raise ValueError("target hair region is too small")

    # Map source face coordinates onto the target face coordinates. No artificial
    # head enlargement: hair geometry follows the actual source-to-target face scale.
    scale_x = sw / max(tw, 1.0)
    scale_y = sh / max(th, 1.0)
    c = sx + (l - tx) * scale_x
    f = sy + (t - ty) * scale_y

    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    alpha_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source_rgb.transform(
        (pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
        resample=rgb_resample, fillcolor=(0, 0, 0),
    )
    source_alpha = _hair_alpha_from_rgba(source_rgba, source_face_box, strong=strong)
    alpha = source_alpha.transform(
        (pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
        resample=alpha_resample, fillcolor=0,
    )

    reference = baseline.crop((l, t, r, b))
    warped = v262._color_match(warped, reference, amount=0.020 if strong else 0.035)
    warped = _harmonize_hair(warped, reference, alpha, strong=strong)

    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=98)

    return payload, {
        "mode": "v274_photoroom_hair_inswapper_face",
        "variant": "hair_identity_strong" if strong else "hair_natural",
        "segmentation": "photoroom_v1_segment_rgba",
        "ownership_model": "photoroom_hair_only_over_inswapper_face_baseline",
        "baseline_owned": "face_forehead_skin_eyes_nose_mouth_cheeks_jaw_ears_neck_body_background",
        "source_owned": "hair_crown_hairline_and_limited_temples_only",
        "blend_model": "opaque_hair_core_soft_real_silhouette_curved_lower_handoff",
        "neck_seam_possible": False,
        "full_head_paste": False,
        "edge_decontamination": True,
        "illumination_harmonization": True,
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale_xy": (round(float(scale_x), 4), round(float(scale_y), 4)),
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v274_photoroom_hair_inswapper_face", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v274_photoroom_hair_inswapper_face", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v274_photoroom_hair_inswapper_face status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
