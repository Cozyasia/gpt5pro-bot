# -*- coding: utf-8 -*-
"""V269 real head cutout matte for isolated Face Swap diagnostic.

V268 proved the compositor path but used a synthetic filled oval, therefore source
background inside that oval still travelled with the head.  V269 keeps the same
alpha-composite architecture but replaces the synthetic oval with a true GrabCut
foreground matte seeded from face geometry.  Outside pixels are hard background;
face/hair cores are hard foreground; only the boundary is estimated.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v269-grabcut-head-alpha-2026-08-13"
_INSTALLED = False


def _real_head_alpha(source_img: Any, face_box: tuple[int, int, int, int], *, strong: bool) -> Any:
    import cv2
    import numpy as np
    from PIL import Image, ImageFilter

    rgb = np.asarray(source_img.convert("RGB"), dtype=np.uint8)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = rgb.shape[:2]
    x, y, fw, fh = [float(v) for v in face_box]
    cx = x + fw * 0.50

    # GC classes: definite bg=0, definite fg=1, probable bg=2, probable fg=3.
    gc = np.full((h, w), cv2.GC_BGD, dtype=np.uint8)

    # Broad anatomical candidate zone only.  This does NOT become alpha itself.
    candidate = np.zeros((h, w), np.uint8)
    cv2.ellipse(candidate, (round(cx), round(y + fh * 0.10)),
                (round(fw * 0.61), round(fh * 0.75)), 0, 0, 360, 255, -1)
    cv2.ellipse(candidate, (round(cx), round(y + fh * 0.55)),
                (round(fw * 0.55), round(fh * 0.64)), 0, 0, 360, 255, -1)
    gc[candidate > 0] = cv2.GC_PR_FGD

    # Definite face core.
    face_core = np.zeros_like(candidate)
    cv2.ellipse(face_core, (round(cx), round(y + fh * 0.54)),
                (round(fw * 0.43), round(fh * 0.53)), 0, 0, 360, 255, -1)
    gc[face_core > 0] = cv2.GC_FGD

    # Definite hair seeds: several compact zones near the forehead/crown, not a filled dome.
    hair_seed = np.zeros_like(candidate)
    cv2.ellipse(hair_seed, (round(cx), round(y - fh * 0.03)),
                (round(fw * 0.34), round(fh * 0.28)), 0, 0, 360, 255, -1)
    cv2.ellipse(hair_seed, (round(cx - fw * 0.20), round(y + fh * 0.10)),
                (round(fw * 0.15), round(fh * 0.24)), 0, 0, 360, 255, -1)
    cv2.ellipse(hair_seed, (round(cx + fw * 0.20), round(y + fh * 0.10)),
                (round(fw * 0.15), round(fh * 0.24)), 0, 0, 360, 255, -1)
    gc[hair_seed > 0] = cv2.GC_FGD

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, gc, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    fg = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    fg *= (candidate > 0).astype(np.uint8)

    # Keep only the component attached to the face centre; this rejects detached room/background islands.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    seed_x = max(0, min(w - 1, int(round(cx))))
    seed_y = max(0, min(h - 1, int(round(y + fh * 0.52))))
    lab = int(labels[seed_y, seed_x])
    if lab > 0:
        fg = (labels == lab).astype(np.uint8)

    # Repair only narrow gaps; never fill the entire anatomical candidate.
    k = np.ones((5, 5), np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=1)

    # Force the inner facial identity area but leave contour/hair determined by segmentation.
    fg = np.maximum(fg, (face_core > 0).astype(np.uint8))

    # Remove anything below the chin; target neck/body must remain untouched.
    bottom = int(round(y + fh * 1.10))
    bottom = max(0, min(h, bottom))
    fg[bottom:, :] = 0

    alpha = Image.fromarray((fg * 255).astype(np.uint8), "L")
    return alpha.filter(ImageFilter.GaussianBlur(2.2 if strong else 2.8))


def _overlay(*, source_full_raw: bytes, source_face_box: tuple[int, int, int, int],
             target_full_raw: bytes, target_face_box: tuple[int, int, int, int],
             baseline_full_raw: bytes, outer_strength: float, core_strength: float) -> tuple[bytes, dict[str, Any]]:
    import numpy as np
    from PIL import Image

    source = fs.image(source_full_raw).convert("RGB")
    target = fs.image(target_full_raw).convert("RGB")
    baseline = fs.image(baseline_full_raw).convert("RGB")
    sx, sy, sw, sh = [float(v) for v in source_face_box]
    tx, ty, tw, th = [float(v) for v in target_face_box]
    strong = bool(outer_strength >= 0.85)
    W, H = target.size

    l = max(0, int(round(tx - tw * 0.24)))
    r = min(W, int(round(tx + tw * 1.24)))
    t = max(0, int(round(ty - th * 0.66)))
    b = min(H, int(round(ty + th * 1.12)))
    pw, ph = r - l, b - t

    scale = 0.5 * ((sw / tw) + (sh / th))
    c = sx + (l - tx) * scale
    f = sy + (t - ty) * scale
    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    rgb_resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
    a_resample = Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else Image.BILINEAR

    warped = source.transform((pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
                              resample=rgb_resample, fillcolor=(0, 0, 0))
    alpha_src = _real_head_alpha(source, source_face_box, strong=strong)
    alpha = alpha_src.transform((pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
                                resample=a_resample, fillcolor=0)

    reference = baseline.crop((l, t, r, b))
    warped = v262._color_match(warped, reference, amount=0.14 if strong else 0.18)

    aa = np.asarray(alpha, np.float32) / 255.0
    local_face_y = ty - t
    chin0 = max(0, min(ph, int(round(local_face_y + th * 0.97))))
    chin1 = max(chin0 + 1, min(ph, int(round(local_face_y + th * 1.10))))
    if chin1 > chin0:
        aa[chin0:chin1] *= np.linspace(1.0, 0.0, chin1 - chin0, dtype=np.float32)[:, None]
    aa[chin1:] = 0.0
    alpha = Image.fromarray(np.clip(aa * 255.0, 0, 255).astype(np.uint8), "L")

    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=97)
    return payload, {
        "mode": "v269_grabcut_head_alpha",
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "grabcut_seeded_real_foreground_connected_component",
        "source_background_rejection": "hard_background_outside_candidate_plus_component_filter",
        "edge_blend": "segmented_alpha_gaussian_plus_chin_fade",
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v269_grabcut_head_owned", False):
        return True
    v265.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v269_grabcut_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v269_grabcut_head_alpha status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
