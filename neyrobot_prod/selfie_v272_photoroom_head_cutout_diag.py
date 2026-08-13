# -*- coding: utf-8 -*-
"""V276 PhotoRoom full-head compositor with opaque identity core.

V275 proved that seamlessClone is the wrong tool for identity transfer: Poisson/mixed
cloning deliberately mixes source gradients with the target and produced the visible
"double exposure" / hybrid face seen in the diagnostic.

V276 keeps the part that worked (PhotoRoom real head silhouette + face-box alignment)
but changes compositing ownership completely:
* the whole source head interior is 100% source-owned and never translucent;
* only a narrow contour band is blended into the target;
* the lower handoff follows a curved jaw/chin gate, not a straight crop;
* low-frequency lighting is matched gently without replacing source facial texture;
* no seamlessClone, no global alpha attenuation, no forehead split.

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

VERSION = "v276-photoroom-opaque-identity-core-2026-08-13"
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
    """Return the real PhotoRoom head silhouette with an anatomical lower handoff."""
    import cv2
    import numpy as np
    from PIL import Image

    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    h, w = alpha.shape
    x, y, fw, fh = [float(v) for v in face_box]

    # Head corridor: keep hair, ears, cheeks and jaw; reject torso/shoulders.
    keep = np.zeros_like(alpha)
    left = max(0, int(round(x - fw * 0.60)))
    right = min(w, int(round(x + fw * 1.60)))
    top = max(0, int(round(y - fh * 1.08)))
    bottom = min(h, int(round(y + fh * 1.20)))
    keep[top:bottom, left:right] = 255
    a = cv2.bitwise_and(alpha, keep)

    # Keep only the connected PhotoRoom foreground component that owns the face.
    binary = (a >= 14).astype(np.uint8)
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

    # Curved jaw/chin handoff: source reaches lowest under the chin centre and
    # leaves earlier at jaw corners. This avoids the horizontal neck seam.
    centre = 1.0 - nx ** 1.65
    curve = y + fh * ((0.92 if strong else 0.90) + (0.18 if strong else 0.16) * centre)
    feather = max(8.0, fh * (0.055 if strong else 0.065))
    jaw_gate = np.clip((curve + feather - yy) / feather, 0.0, 1.0)

    af = (a.astype(np.float32) / 255.0) * jaw_gate
    af[af < 0.018] = 0.0
    return Image.fromarray(np.clip(af * 255.0, 0, 255).astype(np.uint8), "L")


def _harmonize_low_frequency(warped, reference, alpha, *, strong: bool):
    """Match broad illumination only; preserve source identity texture and detail."""
    import cv2
    import numpy as np
    from PIL import Image

    src = np.asarray(warped.convert("RGB"), dtype=np.float32)
    ref = np.asarray(reference.convert("RGB"), dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32) / 255.0

    sigma = max(10.0, min(src.shape[0], src.shape[1]) * 0.036)
    src_low = cv2.GaussianBlur(src, (0, 0), sigma)
    ref_low = cv2.GaussianBlur(ref, (0, 0), sigma)
    delta = np.clip(ref_low - src_low, -24.0, 24.0)

    # Less correction in strong identity mode. Apply only where source is owned.
    amount = 0.12 if strong else 0.18
    owned = np.clip(a[..., None], 0.0, 1.0)
    out = src + delta * amount * owned
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _opaque_identity_integrate(warped, reference, alpha, *, strong: bool):
    """Composite 100% source interior and blend only a thin real-silhouette ring."""
    import cv2
    import numpy as np
    from PIL import Image

    src = np.asarray(warped.convert("RGB"), dtype=np.float32)
    dst = np.asarray(reference.convert("RGB"), dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32) / 255.0
    h, w = a.shape

    # Binary real silhouette from PhotoRoom. We intentionally ignore PhotoRoom's
    # broad semi-transparent interior: it caused ghosting in previous versions.
    silhouette = (a >= 0.055).astype(np.uint8)
    if int(silhouette.sum()) < 500:
        return Image.composite(warped, reference, alpha)

    # Narrow boundary ring only. Everything safely inside the head is exactly 1.0.
    # Width scales with face/head patch but stays small enough to avoid hybrid faces.
    px = max(3, int(round(min(h, w) * (0.010 if strong else 0.013))))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px * 2 + 1, px * 2 + 1))
    core = cv2.erode(silhouette, kernel, iterations=1).astype(np.float32)

    # Distance-to-core gives a controlled feather only outside the opaque core.
    outer = silhouette.astype(np.uint8)
    dist = cv2.distanceTransform((1 - core.astype(np.uint8)) * outer, cv2.DIST_L2, 3)
    width = float(max(2, px))
    ring_alpha = np.clip(1.0 - dist / width, 0.0, 1.0) * outer.astype(np.float32)
    final = np.maximum(core, ring_alpha)

    # Respect fine PhotoRoom antialias only at the extreme outside contour.
    # Never let it reduce the opaque identity core.
    final = np.where(core > 0.5, 1.0, np.minimum(final, np.clip(a * 1.35, 0.0, 1.0)))

    # Small blur ONLY on the transition ring, then restore opaque core to exactly 1.
    sigma = 0.85 if strong else 1.10
    soft = cv2.GaussianBlur(final, (0, 0), sigma)
    final = np.where(core > 0.5, 1.0, soft)
    final *= outer.astype(np.float32)

    fa = np.clip(final, 0.0, 1.0)[..., None]
    out = src * fa + dst * (1.0 - fa)
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

    # Head-sized patch with enough room for crown and jaw transition.
    l = max(0, int(round(tx - tw * 0.72)))
    r = min(W, int(round(tx + tw * 1.72)))
    t = max(0, int(round(ty - th * 1.10)))
    b = min(H, int(round(ty + th * 1.22)))
    pw, ph = r - l, b - t
    if pw < 64 or ph < 64:
        raise ValueError("target head region is too small")

    # Register by detected face geometry. Keep geometry conservative: no artistic
    # enlargement and no independent head warp beyond the source/target face ratio.
    fit = 1.002 if strong else 0.996
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

    # Very light global colour alignment, then low-frequency illumination only.
    warped = v262._color_match(warped, reference, amount=0.012 if strong else 0.022)
    warped = _harmonize_low_frequency(warped, reference, alpha, strong=strong)
    merged = _opaque_identity_integrate(warped, reference, alpha, strong=strong)

    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=98)

    return payload, {
        "mode": "v276_photoroom_opaque_identity_core",
        "variant": "identity_strong" if strong else "natural",
        "segmentation": "photoroom_v1_segment_rgba",
        "ownership_model": "opaque_source_head_core_target_only_at_narrow_boundary",
        "integration": "opaque_identity_core_plus_thin_distance_feather",
        "seamless_clone": False,
        "global_alpha_blend": False,
        "neck_handoff": "curved_u_jaw_gate",
        "forehead_cut": False,
        "hair_cap": False,
        "double_exposure_prevention": True,
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
    if _INSTALLED and getattr(diag.media, "_v276_photoroom_opaque_identity_core", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v276_photoroom_opaque_identity_core", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v276_photoroom_opaque_identity_core status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
