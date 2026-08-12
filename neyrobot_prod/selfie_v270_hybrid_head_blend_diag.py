# -*- coding: utf-8 -*-
"""V270 hybrid head blend for the isolated Face Swap diagnostic.

V269 finally removed the source-room halo by using a real GrabCut foreground matte,
but transplanting the whole segmented head still made the result look pasted on.
V270 changes the composition strategy:

* InSwapper remains the identity base for the face.
* Source RGB is used mainly for hair/crown and a controlled central head region.
* Target ears, neck, shoulders and jaw perimeter stay from the target/baseline.
* The source segmentation is intersected with anatomical soft gates, so background
  can never re-enter through an oversized oval.
* B is the natural mode; C is a stronger identity mode with a wider central bridge.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import selfie_v269_grabcut_head_alpha_diag as v269
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v270-hybrid-head-blend-2026-08-13"
_INSTALLED = False


def _soft_gate(shape: tuple[int, int], face_box: tuple[int, int, int, int], *, strong: bool) -> Any:
    """Build a soft anatomical gate that deliberately excludes ears/neck/jaw rim."""
    import cv2
    import numpy as np

    h, w = shape
    x, y, fw, fh = [float(v) for v in face_box]
    cx = x + fw * 0.50

    gate = np.zeros((h, w), np.float32)

    # Hair/crown gate.  This is where source RGB is most valuable because InSwapper
    # intentionally leaves target hair untouched.
    hair = np.zeros((h, w), np.uint8)
    cv2.ellipse(
        hair,
        (round(cx), round(y - fh * 0.02)),
        (round(fw * (0.53 if strong else 0.50)), round(fh * 0.55)),
        0, 0, 360, 255, -1,
    )
    hair_f = cv2.GaussianBlur(hair, (0, 0), fw * (0.035 if strong else 0.045)).astype(np.float32) / 255.0
    gate = np.maximum(gate, hair_f)

    # Forehead/temple bridge: narrow enough to keep target ears and side silhouette.
    bridge = np.zeros((h, w), np.uint8)
    cv2.ellipse(
        bridge,
        (round(cx), round(y + fh * 0.24)),
        (round(fw * (0.45 if strong else 0.40)), round(fh * (0.43 if strong else 0.34))),
        0, 0, 360, 255, -1,
    )
    bridge_f = cv2.GaussianBlur(bridge, (0, 0), fw * 0.030).astype(np.float32) / 255.0
    bridge_weight = 0.86 if strong else 0.62
    gate = np.maximum(gate, bridge_f * bridge_weight)

    # Strong mode may reinforce the central face, but never the jaw perimeter.  The
    # baseline already carries InSwapper identity, so this is intentionally bounded.
    if strong:
        core = np.zeros((h, w), np.uint8)
        cv2.ellipse(
            core,
            (round(cx), round(y + fh * 0.52)),
            (round(fw * 0.34), round(fh * 0.34)),
            0, 0, 360, 255, -1,
        )
        core_f = cv2.GaussianBlur(core, (0, 0), fw * 0.025).astype(np.float32) / 255.0
        gate = np.maximum(gate, core_f * 0.48)

    # Hard anatomical safety zones: preserve target ears, lower jaw and neck.
    yy, xx = np.mgrid[0:h, 0:w]
    nx = np.abs((xx - cx) / max(fw, 1.0))
    # Sides become progressively target-owned below the temples.
    side_fade = np.ones((h, w), np.float32)
    temple_y = y + fh * 0.10
    lower_y = y + fh * 0.82
    vertical = np.clip((yy - temple_y) / max(lower_y - temple_y, 1.0), 0.0, 1.0)
    side_limit = (0.50 if strong else 0.46) - vertical * (0.12 if strong else 0.15)
    side_soft = np.clip((side_limit + 0.055 - nx) / 0.055, 0.0, 1.0)
    side_fade *= np.where(yy > temple_y, side_soft, 1.0)
    gate *= side_fade

    # Fade source ownership out before the chin so target neck and jaw join stay native.
    chin0 = y + fh * (0.79 if strong else 0.70)
    chin1 = y + fh * (0.98 if strong else 0.90)
    vf = np.ones((h, w), np.float32)
    band = (yy >= chin0) & (yy < chin1)
    vf[band] = 1.0 - ((yy[band] - chin0) / max(chin1 - chin0, 1.0))
    vf[yy >= chin1] = 0.0
    gate *= vf

    return np.clip(gate, 0.0, 1.0)


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image

    source = fs.image(source_full_raw).convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")
    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    strong = bool(outer_strength >= 0.85)
    W, H = baseline.size

    # Smaller patch than V269; there is no reason to touch target shoulders or neck.
    l = max(0, int(round(tx - tw * 0.18)))
    r = min(W, int(round(tx + tw * 1.18)))
    t = max(0, int(round(ty - th * 0.68)))
    b = min(H, int(round(ty + th * 0.98)))
    pw, ph = r - l, b - t

    scale = 0.5 * ((sw / tw) + (sh / th))
    c = sx + (l - tx) * scale
    f = sy + (t - ty) * scale
    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    a_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source.transform(
        (pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
        resample=rgb_resample, fillcolor=(0, 0, 0),
    )

    # V269 supplies the real source foreground segmentation.  We then intersect it
    # with V270's anatomical ownership gate instead of using the entire head matte.
    seg_full = v269._real_head_alpha(source, source_face_box, strong=strong)
    seg = seg_full.transform(
        (pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
        resample=a_resample, fillcolor=0,
    )
    seg_a = np.asarray(seg, np.float32) / 255.0

    # Build gate in target coordinates, then crop to the local patch.
    gate_full = _soft_gate((H, W), target_face_box, strong=strong)
    gate = gate_full[t:b, l:r]
    aa = np.clip(seg_a * gate, 0.0, 1.0)

    # Natural mode is deliberately conservative.  Strong mode owns more hair/temple
    # texture, while the baseline continues to own ears, jaw rim and neck.
    aa *= (0.90 if strong else 0.78)

    reference = baseline.crop((l, t, r, b))
    warped = v262._color_match(warped, reference, amount=0.13 if strong else 0.18)

    alpha = Image.fromarray(np.clip(aa * 255.0, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v270_hybrid_head_blend",
        "variant": "identity_strong" if strong else "natural",
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "v269_grabcut_intersect_v270_anatomical_gate",
        "target_owned": "ears_neck_shoulders_jaw_perimeter",
        "source_owned": "hair_crown_forehead_central_identity_bridge",
        "edge_blend": "segmented_alpha_times_soft_anatomical_gate",
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v270_hybrid_head_owned", False):
        return True
    v265.install()
    v269.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v270_hybrid_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v270_hybrid_head_blend status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
