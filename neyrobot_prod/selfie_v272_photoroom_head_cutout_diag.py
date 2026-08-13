# -*- coding: utf-8 -*-
"""V272 PhotoRoom silhouette head compositor for isolated Face Swap diagnostic.

The source head is no longer invented by an ellipse/GrabCut mask. We ask the same
PhotoRoom segmentation service used by the background-removal feature for a real
RGBA person cutout, retain the real alpha silhouette around the head, align it to
the target face box, and feather only a very narrow contour band.
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v272-photoroom-head-cutout-2026-08-13"
_INSTALLED = False


def _photoroom_rgba(source_raw: bytes):
    """Return PhotoRoom's real RGBA cutout. Fail loudly: no silent GrabCut fallback."""
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
    """Keep PhotoRoom silhouette; remove torso/neck without drawing a fake head oval."""
    import cv2
    import numpy as np
    from PIL import Image

    alpha = np.asarray(rgba.getchannel("A"), np.uint8)
    h, w = alpha.shape
    x, y, fw, fh = [float(v) for v in face_box]

    # PhotoRoom owns the silhouette. Geometry below only excludes body and distant
    # foreground; it never creates foreground where PhotoRoom says background.
    keep = np.zeros_like(alpha)
    left = max(0, int(round(x - fw * (0.55 if strong else 0.48))))
    right = min(w, int(round(x + fw * (1.55 if strong else 1.48))))
    top = max(0, int(round(y - fh * (1.00 if strong else 0.92))))
    bottom = min(h, int(round(y + fh * (1.10 if strong else 1.04))))
    keep[top:bottom, left:right] = 255
    a = cv2.bitwise_and(alpha, keep)

    # Select only the connected foreground component that intersects the face box.
    binary = (a >= 24).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    fx0, fy0 = max(0, int(x)), max(0, int(y))
    fx1, fy1 = min(w, int(x + fw)), min(h, int(y + fh))
    face_labels = labels[fy0:fy1, fx0:fx1]
    ids, freq = np.unique(face_labels[face_labels > 0], return_counts=True)
    if len(ids):
        chosen = int(ids[int(np.argmax(freq))])
        a = np.where(labels == chosen, a, 0).astype(np.uint8)

    # The only synthetic boundary is the lower neck cut. It is horizontal and
    # feathered over a small band; hair/ears/temples remain the real PhotoRoom edge.
    yy = np.arange(h, dtype=np.float32)[:, None]
    cut0 = y + fh * (0.94 if strong else 0.90)
    cut1 = y + fh * (1.08 if strong else 1.02)
    neck = np.ones((h, 1), np.float32)
    band = (yy >= cut0) & (yy < cut1)
    neck[band] = 1.0 - (yy[band] - cut0) / max(cut1 - cut0, 1.0)
    neck[yy >= cut1] = 0.0
    af = (a.astype(np.float32) / 255.0) * neck

    # Opaque interior. Feather only a narrow contour band, so the face never becomes
    # translucent and cannot create the double-face/ghosting seen in V270/V271.
    hard = (af >= 0.72).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    core = cv2.erode(hard, kernel, iterations=max(1, int(round(fw * 0.004))))
    edge = np.clip(af - core.astype(np.float32), 0.0, 1.0)
    edge = cv2.GaussianBlur(edge, (0, 0), max(0.7, fw * 0.0045))
    final = np.maximum(core.astype(np.float32), edge)
    final[final >= 0.94] = 1.0
    return Image.fromarray(np.clip(final * 255.0, 0, 255).astype(np.uint8), "L")


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image

    source_rgba = _photoroom_rgba(source_full_raw)
    source = source_rgba.convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")
    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    strong = bool(outer_strength >= 0.85)
    W, H = baseline.size

    # Patch bounds only limit work. Actual silhouette comes exclusively from PhotoRoom.
    l = max(0, int(round(tx - tw * 0.58)))
    r = min(W, int(round(tx + tw * 1.58)))
    t = max(0, int(round(ty - th * 1.02)))
    b = min(H, int(round(ty + th * 1.10)))
    pw, ph = r - l, b - t

    # Face-box similarity alignment. Unlike V271, use independent X/Y scale so head
    # width and height land on the target without forcing an oversized pasted head.
    scale_x = sw / max(tw, 1.0)
    scale_y = sh / max(th, 1.0)
    c = sx + (l - tx) * scale_x
    f = sy + (t - ty) * scale_y
    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    # PIL.Image.transform does not accept LANCZOS; BICUBIC is the highest-quality
    # supported affine resampler here. Keep alpha on BILINEAR to avoid hard ringing.
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    a_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source.transform((pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
                              resample=rgb_resample, fillcolor=(0, 0, 0))
    src_alpha = _head_alpha_from_rgba(source_rgba, source_face_box, strong=strong)
    alpha = src_alpha.transform((pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
                                resample=a_resample, fillcolor=0)

    reference = baseline.crop((l, t, r, b))
    # Very small adaptation only. Identity, hair texture and skin texture stay source-owned.
    warped = v262._color_match(warped, reference, amount=0.045 if strong else 0.065)
    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v272_photoroom_head_cutout",
        "variant": "photoroom_strong" if strong else "photoroom_natural",
        "segmentation": "photoroom_v1_segment_rgba",
        "silhouette_owner": "photoroom_alpha",
        "alignment": "face_box_independent_xy",
        "blend_model": "opaque_interior_narrow_contour_feather",
        "source_owned": "face_hair_real_head_silhouette",
        "target_owned": "background_body_shoulders_and_neck_below_cut",
        "no_grabcut": True,
        "no_head_ellipse": True,
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale_xy": (round(float(scale_x), 4), round(float(scale_y), 4)),
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v272_photoroom_head_owned", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v272_photoroom_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v272_photoroom_head_cutout status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
