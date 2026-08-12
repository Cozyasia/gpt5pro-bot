# -*- coding: utf-8 -*-
"""V271 opaque full-head cutout for the isolated Face Swap diagnostic.

V270 proved that translucent source RGB over the InSwapper baseline creates a
visible double-face/ghosting artifact.  V271 changes the blend model completely:

* Use the V269 GrabCut foreground matte to isolate the source head.
* Replace the target head with an OPAQUE source-head core.
* Feather only the narrow silhouette boundary; never lower opacity across the face.
* Stop the matte at the chin so target neck/shoulders remain native.
* B uses a tighter natural silhouette; C allows a slightly wider hair/jaw envelope.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v262_full_head_identity_diag as v262
from neyrobot_prod import selfie_v265_clean_head_transplant_diag as v265
from neyrobot_prod import selfie_v269_grabcut_head_alpha_diag as v269
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v271-opaque-head-cutout-2026-08-13"
_INSTALLED = False


def _anatomical_head_gate(shape: tuple[int, int], face_box: tuple[int, int, int, int], *, strong: bool) -> Any:
    """Continuous whole-head envelope with a hard stop before the neck/shoulders."""
    import cv2
    import numpy as np

    h, w = shape
    x, y, fw, fh = [float(v) for v in face_box]
    cx = x + fw * 0.50
    cy = y + fh * 0.34

    hard = np.zeros((h, w), np.uint8)
    # Full head: hair, temples, ears/cheeks and chin.  Strong mode is only a few
    # pixels wider; neither mode extends into shoulders.
    ax = fw * (0.60 if strong else 0.575)
    ay = fh * (0.73 if strong else 0.70)
    cv2.ellipse(hard, (round(cx), round(cy)), (round(ax), round(ay)), 0, 0, 360, 255, -1)

    # Flatten the lower envelope at the chin/upper-jaw boundary.  This is the key
    # difference from the old oversized oval, which dragged source neck/background.
    yy = np.arange(h, dtype=np.float32)[:, None]
    chin0 = y + fh * (0.94 if strong else 0.91)
    chin1 = y + fh * (1.03 if strong else 0.99)
    vf = np.ones((h, 1), np.float32)
    band = (yy >= chin0) & (yy < chin1)
    vf[band] = 1.0 - ((yy[band] - chin0) / max(chin1 - chin0, 1.0))
    vf[yy >= chin1] = 0.0

    # Narrow feather only around the silhouette.  Interior stays exactly 1.0.
    sigma = max(1.5, fw * (0.010 if strong else 0.012))
    soft = cv2.GaussianBlur(hard, (0, 0), sigma).astype(np.float32) / 255.0
    return np.clip(soft * vf, 0.0, 1.0)


def _harden_alpha(alpha: Any, face_width: float, *, strong: bool) -> Any:
    """Convert a soft matte into opaque interior + narrow anti-aliased edge."""
    import cv2
    import numpy as np

    a = np.clip(alpha.astype(np.float32), 0.0, 1.0)

    # Push most of the foreground to full opacity.  This removes the double-face
    # seen in V270, where the entire source head was multiplied by 0.78/0.90.
    lo = 0.10 if strong else 0.13
    hi = 0.58 if strong else 0.62
    a = np.clip((a - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    a = a * a * (3.0 - 2.0 * a)  # smoothstep
    a[a >= (0.74 if strong else 0.78)] = 1.0

    # Final edge blur is intentionally tiny: only seam anti-aliasing, not ghosting.
    sigma = max(0.8, face_width * (0.006 if strong else 0.008))
    a = cv2.GaussianBlur(a, (0, 0), sigma)
    a = np.clip(a, 0.0, 1.0)
    a[a >= 0.92] = 1.0
    return a


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

    # Whole-head patch, but still bounded tightly enough that shoulders can never be
    # touched by this compositor.
    l = max(0, int(round(tx - tw * (0.27 if strong else 0.24))))
    r = min(W, int(round(tx + tw * (1.27 if strong else 1.24))))
    t = max(0, int(round(ty - th * (0.74 if strong else 0.71))))
    b = min(H, int(round(ty + th * (1.06 if strong else 1.02))))
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

    seg_full = v269._real_head_alpha(source, source_face_box, strong=strong)
    seg = seg_full.transform(
        (pw, ph), affine, (scale, 0.0, c, 0.0, scale, f),
        resample=a_resample, fillcolor=0,
    )
    seg_a = np.asarray(seg, np.float32) / 255.0

    gate_full = _anatomical_head_gate((H, W), target_face_box, strong=strong)
    gate = gate_full[t:b, l:r]
    aa = _harden_alpha(seg_a * gate, tw, strong=strong)

    reference = baseline.crop((l, t, r, b))
    # Keep source identity/skin/hair intact.  A small color adaptation is enough to
    # remove lighting mismatch without turning the source face translucent.
    warped = v262._color_match(warped, reference, amount=0.07 if strong else 0.10)

    alpha = Image.fromarray(np.clip(aa * 255.0, 0, 255).astype(np.uint8), "L")
    merged = Image.composite(warped, reference, alpha)
    output = baseline.copy()
    output.paste(merged, (l, t))
    payload = fs.jpeg(output, max_side=2048, quality=97)

    return payload, {
        "mode": "v271_opaque_head_cutout",
        "variant": "opaque_strong" if strong else "opaque_natural",
        "target_patch": (l, t, r, b),
        "source_face_box": tuple(int(v) for v in source_face_box),
        "target_face_box": tuple(int(v) for v in target_face_box),
        "scale": round(float(scale), 4),
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "segmentation": "v269_grabcut_times_v271_head_gate",
        "blend_model": "opaque_core_narrow_feather_only",
        "target_owned": "neck_shoulders_outside_head_silhouette",
        "source_owned": "entire_segmented_head_including_face_and_hair",
        "ghosting_prevention": "no_global_alpha_attenuation",
    }


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(diag.media, "_v271_opaque_head_owned", False):
        return True
    v265.install()
    v269.install()
    v262._full_head_overlay = _overlay
    media = v262.media
    setattr(media, "_v271_opaque_head_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v271_opaque_head_cutout status=installed version=%s", VERSION)
    return True


media = v262.media
__all__ = ["VERSION", "media", "install"]
