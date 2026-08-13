# -*- coding: utf-8 -*-
"""V273 PhotoRoom head compositor for the isolated Face Swap diagnostic.

V272 proved that PhotoRoom gives the right real head silhouette. V273 keeps that
silhouette but fixes the two remaining visual defects: the horizontal neck seam and
the pasted-sticker look. The source head remains identity-owned; only low-frequency
illumination and the outer transition band are adapted to the target photograph.
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v273-photoroom-seam-harmonized-2026-08-13"
_INSTALLED = False


def _photoroom_rgba(source_raw: bytes):
    """Return PhotoRoom's real RGBA cutout. No synthetic segmentation fallback."""
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
    """PhotoRoom silhouette with an anatomical curved jaw/neck handoff."""
    import cv2
    import numpy as np
    from PIL import Image

    alpha = np.asarray(rgba.getchannel("A"), np.uint8)
    h, w = alpha.shape
    x, y, fw, fh = [float(v) for v in face_box]

    # PhotoRoom remains the sole owner of foreground/background classification.
    keep = np.zeros_like(alpha)
    left = max(0, int(round(x - fw * (0.54 if strong else 0.50))))
    right = min(w, int(round(x + fw * (1.54 if strong else 1.50))))
    top = max(0, int(round(y - fh * (1.00 if strong else 0.96))))
    bottom = min(h, int(round(y + fh * 1.14)))
    keep[top:bottom, left:right] = 255
    a = cv2.bitwise_and(alpha, keep)

    # Keep only the PhotoRoom foreground component that actually owns the face.
    binary = (a >= 20).astype(np.uint8)
    _, labels, _, _ = cv2.connectedComponentsWithStats(binary, 8)
    fx0, fy0 = max(0, int(x)), max(0, int(y))
    fx1, fy1 = min(w, int(x + fw)), min(h, int(y + fh))
    face_labels = labels[fy0:fy1, fx0:fx1]
    ids, freq = np.unique(face_labels[face_labels > 0], return_counts=True)
    if len(ids):
        chosen = int(ids[int(np.argmax(freq))])
        a = np.where(labels == chosen, a, 0).astype(np.uint8)

    # Anatomical lower handoff. V272 used one horizontal line and that line was
    # visible under the chin. Here the source extends lower in the centre and exits
    # earlier toward both jaw corners, producing a shallow U-shaped transition.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = x + fw * 0.50
    dx = np.abs((xx - cx) / max(fw * 0.58, 1.0))
    dx = np.clip(dx, 0.0, 1.0)
    centre_bonus = (1.0 - dx ** 1.65)
    curve = y + fh * ((0.925 if strong else 0.915) + (0.155 if strong else 0.145) * centre_bonus)
    feather = fh * (0.085 if strong else 0.095)
    neck_gate = np.clip((curve + feather - yy) / max(feather, 1.0), 0.0, 1.0)

    af = (a.astype(np.float32) / 255.0) * neck_gate

    # Opaque identity core, but a wider soft contour than V272. This removes the
    # cardboard-cutout edge while keeping eyes, nose, mouth, skin and hair texture opaque.
    hard = (af >= 0.76).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    erode_iter = max(1, int(round(fw * (0.0035 if strong else 0.0045))))
    core = cv2.erode(hard, kernel, iterations=erode_iter)
    edge = np.clip(af - core.astype(np.float32), 0.0, 1.0)
    sigma = max(1.0, fw * (0.0065 if strong else 0.0080))
    edge = cv2.GaussianBlur(edge, (0, 0), sigma)
    final = np.maximum(core.astype(np.float32), edge)
    final[final >= 0.965] = 1.0
    return Image.fromarray(np.clip(final * 255.0, 0, 255).astype(np.uint8), "L")


def _harmonize_low_frequency(warped, reference, alpha, *, strong: bool):
    """Match target illumination without washing out source identity/detail."""
    import cv2
    import numpy as np
    from PIL import Image

    src = np.asarray(warped, np.float32)
    ref = np.asarray(reference, np.float32)
    a = np.asarray(alpha, np.float32) / 255.0

    # Only low spatial frequencies are transferred. Fine skin/hair detail remains source.
    sigma = max(8.0, min(src.shape[0], src.shape[1]) * 0.030)
    src_low = cv2.GaussianBlur(src, (0, 0), sigma)
    ref_low = cv2.GaussianBlur(ref, (0, 0), sigma)
    delta = np.clip(ref_low - src_low, -34.0, 34.0)
    amount = 0.24 if strong else 0.34
    out = src + delta * amount

    # Edge decontamination: near the alpha transition, gently inherit target colour.
    # This removes bright/dark source-background fringe without touching the face core.
    edge_weight = np.clip(4.0 * a * (1.0 - a), 0.0, 1.0)[..., None]
    edge_mix = 0.16 if strong else 0.24
    out = out * (1.0 - edge_weight * edge_mix) + ref * (edge_weight * edge_mix)

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    from PIL import Image

    source_rgba = _photoroom_rgba(source_full_raw)
    source = source_rgba.convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")
    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    strong = bool(outer_strength >= 0.85)
    W, H = baseline.size

    # Smaller work patch than V272; enough for hair and jaw, not almost the whole frame.
    l = max(0, int(round(tx - tw * 0.50)))
    r = min(W, int(round(tx + tw * 1.50)))
    t = max(0, int(round(ty - th * 1.00)))
    b = min(H, int(round(ty + th * 1.12)))
    pw, ph = r - l, b - t

    # Slight natural-size correction. V272 alignment was mathematically exact but the
    # transplanted head read a little oversized. Natural mode reduces it ~2%; strong ~1%.
    fit = 1.010 if strong else 1.022
    scale_x = (sw / max(tw, 1.0)) * fit
    scale_y = (sh / max(th, 1.0)) * fit
    c = sx + (l - tx) * scale_x + sw * (1.0 - fit) * 0.50
    f = sy + (t - ty) * scale_y + sh * (1.0 - fit) * 0.48

    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    a_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source.transform((pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
                              resample=rgb_resample, fillcolor=(0, 0, 0))
    src_alpha = _head_alpha_from_rgba(source_rgba, source_face_box, strong=strong)
    alpha = src_alpha.transform((pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f),
                                resample=a_resample, fillcolor=0)

    reference = baseline.crop((l, t, r, b))
    # First a tiny global colour correction, then spatial low-frequency harmonisation.
    warped = v262._color_match(warped, reference, amount=0.035 if strong else 0.050)
    warped = _harmonize_low_frequency(warped, reference, alpha, strong=strong)

    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=98)

    return payload, {
        "mode": "v273_photoroom_seam_harmonized",
        "variant": "identity_strong" if strong else "natural_integrated",
        "segmentation": "photoroom_v1_segment_rgba",
        "silhouette_owner": "photoroom_alpha",
        "alignment": "face_box_xy_with_natural_size_correction",
        "blend_model": "opaque_identity_core_soft_contour_plus_low_frequency_harmonization",
        "neck_handoff": "curved_jaw_u_gate",
        "edge_decontamination": True,
        "illumination_harmonization": True,
        "source_owned": "face_hair_skin_texture_real_head_silhouette",
        "target_owned": "background_body_shoulders_neck_below_anatomical_handoff",
        "no_grabcut": True,
        "no_head_ellipse": True,
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale_xy": (round(float(scale_x), 4), round(float(scale_y), 4)),
        "fit": fit,
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v273_photoroom_seam_harmonized", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v273_photoroom_seam_harmonized", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v273_photoroom_seam_harmonized status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
