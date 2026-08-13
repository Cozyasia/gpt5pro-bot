# -*- coding: utf-8 -*-
"""V275 PhotoRoom full-head + seamless-clone compositor.

V274 regressed because it split ownership through the forehead and pasted a hair cap.
V275 returns to the V272/V273 idea that worked best visually: PhotoRoom owns the real
source head silhouette. The difference is integration: the head is no longer pasted
with a visible alpha seam. Instead we align the full head by face geometry, build an
anatomical jaw handoff, pre-harmonize only low frequencies, then use OpenCV mixed
seamless cloning for the opaque head interior. A very narrow PhotoRoom-alpha contour
is composited afterwards only to recover fine hair/flyaway silhouette.

Production AI-selfie remains untouched; this patches only the isolated Face Swap test.
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v275-photoroom-full-head-seamless-clone-2026-08-13"
_INSTALLED = False


def _photoroom_rgba(source_raw: bytes):
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


def _head_alpha_from_rgba(rgba, face_box: tuple[int, int, int, int], *, strong: bool):
    """Keep the real PhotoRoom head silhouette and hand off below the jaw with a U curve."""
    import cv2
    import numpy as np
    from PIL import Image

    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    h, w = alpha.shape
    x, y, fw, fh = [float(v) for v in face_box]

    # Wide corridor around the real head; body/shoulders are never source-owned.
    keep = np.zeros_like(alpha)
    left = max(0, int(round(x - fw * 0.58)))
    right = min(w, int(round(x + fw * 1.58)))
    top = max(0, int(round(y - fh * 1.04)))
    bottom = min(h, int(round(y + fh * 1.18)))
    keep[top:bottom, left:right] = 255
    a = cv2.bitwise_and(alpha, keep)

    # Keep connected PhotoRoom foreground component that overlaps the detected face.
    binary = (a >= 16).astype(np.uint8)
    count, labels, _, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count > 1:
        fx0, fy0 = max(0, int(x)), max(0, int(y))
        fx1, fy1 = min(w, int(x + fw)), min(h, int(y + fh))
        face_labels = labels[fy0:fy1, fx0:fx1]
        ids, freq = np.unique(face_labels[face_labels > 0], return_counts=True)
        if len(ids):
            chosen = int(ids[int(np.argmax(freq))])
            a = np.where(labels == chosen, a, 0).astype(np.uint8)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = x + fw * 0.50
    nx = np.clip(np.abs((xx - cx) / max(fw * 0.62, 1.0)), 0.0, 1.0)

    # Source extends lowest under the chin centre, but exits earlier at jaw corners.
    centre = 1.0 - nx ** 1.55
    curve = y + fh * ((0.93 if strong else 0.91) + (0.19 if strong else 0.17) * centre)
    feather = max(10.0, fh * (0.075 if strong else 0.090))
    jaw_gate = np.clip((curve + feather - yy) / feather, 0.0, 1.0)

    af = (a.astype(np.float32) / 255.0) * jaw_gate

    # Clean only tiny halo pixels; preserve genuine fine hair alpha.
    af[af < 0.025] = 0.0
    return Image.fromarray(np.clip(af * 255.0, 0, 255).astype(np.uint8), "L")


def _harmonize_low_frequency(warped, reference, alpha, *, strong: bool):
    import cv2
    import numpy as np
    from PIL import Image

    src = np.asarray(warped.convert("RGB"), dtype=np.float32)
    ref = np.asarray(reference.convert("RGB"), dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32) / 255.0

    sigma = max(9.0, min(src.shape[0], src.shape[1]) * 0.032)
    src_low = cv2.GaussianBlur(src, (0, 0), sigma)
    ref_low = cv2.GaussianBlur(ref, (0, 0), sigma)
    delta = np.clip(ref_low - src_low, -30.0, 30.0)
    amount = 0.20 if strong else 0.28
    out = src + delta * amount

    # Only transition pixels borrow a little target colour; identity core is untouched.
    band = np.clip(4.0 * a * (1.0 - a), 0.0, 1.0)[..., None]
    mix = 0.10 if strong else 0.15
    out = out * (1.0 - band * mix) + ref * (band * mix)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _seamless_integrate(warped, reference, alpha, *, strong: bool):
    """Clone opaque head interior into target and restore only the fine PhotoRoom contour."""
    import cv2
    import numpy as np
    from PIL import Image

    src_rgb = np.asarray(warped.convert("RGB"), dtype=np.uint8)
    dst_rgb = np.asarray(reference.convert("RGB"), dtype=np.uint8)
    a = np.asarray(alpha, dtype=np.uint8)
    h, w = a.shape

    # Mixed clone mask excludes the semi-transparent hair fringe and the feather tail.
    threshold = 104 if strong else 118
    core = np.where(a >= threshold, 255, 0).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, kernel, iterations=1)
    core = cv2.erode(core, kernel, iterations=1)

    ys, xs = np.where(core > 0)
    if len(xs) < 500:
        # Conservative fallback: soft alpha composite, never rectangular paste.
        return Image.composite(warped, reference, alpha)

    # Fill outside source mask with target so source-background gradients cannot leak.
    safe_src = src_rgb.copy()
    outside = core == 0
    safe_src[outside] = dst_rgb[outside]

    # seamlessClone expects BGR.
    src_bgr = cv2.cvtColor(safe_src, cv2.COLOR_RGB2BGR)
    dst_bgr = cv2.cvtColor(dst_rgb, cv2.COLOR_RGB2BGR)
    center = (w // 2, h // 2)
    try:
        cloned_bgr = cv2.seamlessClone(src_bgr, dst_bgr, core, center, cv2.MIXED_CLONE)
        cloned = cv2.cvtColor(cloned_bgr, cv2.COLOR_BGR2RGB)
    except cv2.error:
        return Image.composite(warped, reference, alpha)

    # Restore only the narrow real silhouette that clone intentionally excludes.
    af = a.astype(np.float32) / 255.0
    coref = core.astype(np.float32) / 255.0
    fringe = np.clip(af - coref, 0.0, 1.0)
    fringe = cv2.GaussianBlur(fringe, (0, 0), max(0.8, w * 0.0022))
    fringe = np.clip(fringe * (0.80 if strong else 0.72), 0.0, 1.0)[..., None]

    out = cloned.astype(np.float32) * (1.0 - fringe) + src_rgb.astype(np.float32) * fringe
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    from PIL import Image

    source_rgba = _photoroom_rgba(source_full_raw)
    source_rgb = source_rgba.convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")

    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    strong = bool(outer_strength >= 0.85)
    W, H = baseline.size

    # Head-sized patch; never full frame and never cut through the forehead.
    l = max(0, int(round(tx - tw * 0.70)))
    r = min(W, int(round(tx + tw * 1.70)))
    t = max(0, int(round(ty - th * 1.08)))
    b = min(H, int(round(ty + th * 1.22)))
    pw, ph = r - l, b - t
    if pw < 64 or ph < 64:
        raise ValueError("target head region is too small")

    # Face-box registration. Keep source proportions; only a tiny fit correction is allowed.
    fit = 1.006 if strong else 0.998
    scale_x = (sw / max(tw, 1.0)) * fit
    scale_y = (sh / max(th, 1.0)) * fit
    c = sx + (l - tx) * scale_x + sw * (1.0 - fit) * 0.50
    f = sy + (t - ty) * scale_y + sh * (1.0 - fit) * 0.50

    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    alpha_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source_rgb.transform(
        (pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
        resample=rgb_resample, fillcolor=(0, 0, 0),
    )
    source_alpha = _head_alpha_from_rgba(source_rgba, source_face_box, strong=strong)
    alpha = source_alpha.transform(
        (pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
        resample=alpha_resample, fillcolor=0,
    )

    reference = baseline.crop((l, t, r, b))
    warped = v262._color_match(warped, reference, amount=0.025 if strong else 0.040)
    warped = _harmonize_low_frequency(warped, reference, alpha, strong=strong)
    merged = _seamless_integrate(warped, reference, alpha, strong=strong)

    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=98)

    return payload, {
        "mode": "v275_photoroom_full_head_seamless_clone",
        "variant": "identity_strong" if strong else "natural",
        "segmentation": "photoroom_v1_segment_rgba",
        "ownership_model": "full_source_head_inside_real_photoroom_silhouette",
        "integration": "opencv_mixed_seamless_clone_plus_narrow_alpha_fringe",
        "neck_handoff": "curved_u_jaw_gate",
        "forehead_cut": False,
        "hair_cap": False,
        "full_head_identity": True,
        "target_body_background_preserved": True,
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale_xy": (round(float(scale_x), 4), round(float(scale_y), 4)),
        "fit": fit,
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v275_photoroom_full_head_seamless_clone", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v275_photoroom_full_head_seamless_clone", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v275_photoroom_full_head_seamless_clone status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
