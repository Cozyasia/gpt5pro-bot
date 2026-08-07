# -*- coding: utf-8 -*-
"""Photorealistic post-processing for PiAPI/Qubico Face Swap.

This layer does NOT call a model and does NOT detect/replace identity. It only
integrates the already-swapped PiAPI result back into the untouched target photo.

Design goals:
- preserve the target image outside the pixels actually changed by Face Swap;
- derive the blend mask from target/result difference, not from Haar/OpenCV face
  detection (which is intentionally non-blocking in the diagnostic flow);
- softly feather the changed region to remove rectangular/halo seams;
- gently adapt luminance/chroma to the target lighting;
- restore a small amount of target high-frequency texture so skin does not look
  waxy while keeping the PiAPI identity result authoritative.

The function is deliberately conservative. If a reliable changed region cannot
be isolated, it returns the raw PiAPI result rather than inventing a mask.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

VERSION = "v252-photorealistic-diff-mask-blend-2026-08-08"


@dataclass(frozen=True)
class QualityStats:
    applied: bool
    changed_ratio: float
    bbox: tuple[int, int, int, int] | None
    threshold: float
    reason: str = ""


def _pil(raw: bytes):
    from PIL import Image, ImageOps
    return ImageOps.exif_transpose(Image.open(BytesIO(bytes(raw or b"")))).convert("RGB")


def _jpeg(image: Any, quality: int = 96) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue()


def _largest_change_mask(target_rgb: Any, swapped_rgb: Any):
    """Return (soft alpha mask, stats) or (None, stats).

    JPEG recompression creates low-amplitude differences everywhere. We therefore
    threshold an intentionally blurred RGB delta and keep the dominant meaningful
    connected component. The mask is then dilated and feathered so the boundary
    lies in visually stable surrounding pixels rather than on a hard face edge.
    """
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    h, w = target_rgb.shape[:2]
    if h < 64 or w < 64 or swapped_rgb.shape[:2] != (h, w):
        return None, QualityStats(False, 0.0, None, 0.0, "invalid_or_mismatched_dimensions")

    delta = cv2.absdiff(target_rgb, swapped_rgb).astype(np.float32)
    # Perceptual-ish RGB delta. Blur suppresses JPEG block/noise differences.
    gray = 0.299 * delta[:, :, 0] + 0.587 * delta[:, :, 1] + 0.114 * delta[:, :, 2]
    sigma = max(1.2, min(h, w) / 650.0)
    gray = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma, sigmaY=sigma)

    p90 = float(np.percentile(gray, 90.0))
    p97 = float(np.percentile(gray, 97.0))
    threshold = max(13.0, min(36.0, max(p90 * 1.35, p97 * 0.72)))
    binary = (gray >= threshold).astype(np.uint8) * 255

    k = max(3, int(round(min(h, w) * 0.008)))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    image_area = float(h * w)
    candidates: list[tuple[float, int]] = []
    for idx in range(1, count):
        x, y, cw, ch, area = [int(v) for v in stats[idx]]
        ratio = area / image_area
        if ratio < 0.0015 or ratio > 0.48:
            continue
        # Prefer a compact, strong component. FaceSwap should not own most of frame.
        local = gray[labels == idx]
        strength = float(local.mean()) if local.size else 0.0
        score = float(area) * max(1.0, strength)
        candidates.append((score, idx))

    if not candidates:
        return None, QualityStats(False, 0.0, None, threshold, "no_reliable_change_component")

    idx = max(candidates)[1]
    component = (labels == idx).astype(np.uint8) * 255
    x, y, cw, ch, area = [int(v) for v in stats[idx]]

    # Expand beyond the strongest changed pixels, but not to a giant rectangular crop.
    dilate_px = max(7, int(round(min(h, w) * 0.018)))
    dk = dilate_px * 2 + 1
    dkernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dk, dk))
    expanded = cv2.dilate(component, dkernel, iterations=1)

    feather = max(7.0, min(h, w) * 0.012)
    alpha = cv2.GaussianBlur(expanded.astype(np.float32) / 255.0, (0, 0), sigmaX=feather, sigmaY=feather)
    alpha = np.clip(alpha, 0.0, 1.0)

    changed_ratio = float((alpha > 0.10).sum()) / image_area
    if changed_ratio > 0.58:
        return None, QualityStats(False, changed_ratio, (x, y, cw, ch), threshold, "mask_too_large")
    return alpha, QualityStats(True, changed_ratio, (x, y, cw, ch), threshold, "ok")


def _lighting_match(target_rgb: Any, swapped_rgb: Any, alpha: Any):
    """Gently match FaceSwap lighting/chroma to target inside the blend region."""
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    mask = alpha > 0.28
    if int(mask.sum()) < 256:
        return swapped_rgb.astype(np.float32)

    target_lab = cv2.cvtColor(target_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    swap_lab = cv2.cvtColor(swapped_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    adjusted = swap_lab.copy()

    # Partial mean correction only. Full histogram matching tends to change identity
    # and skin characteristics; the target contributes lighting context, not identity.
    strengths = (0.42, 0.32, 0.32)
    for c, strength in enumerate(strengths):
        tm = float(target_lab[:, :, c][mask].mean())
        sm = float(swap_lab[:, :, c][mask].mean())
        shift = max(-18.0, min(18.0, tm - sm)) * strength
        adjusted[:, :, c] = np.clip(adjusted[:, :, c] + shift, 0.0, 255.0)

    return cv2.cvtColor(adjusted.astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)


def _restore_texture(target_rgb: Any, corrected_rgb: Any, alpha: Any):
    """Add a small amount of target high-frequency luminance texture."""
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    target_f = target_rgb.astype(np.float32)
    blur = cv2.GaussianBlur(target_f, (0, 0), sigmaX=1.25, sigmaY=1.25)
    high = target_f - blur
    texture_alpha = np.clip(alpha[..., None] * 0.14, 0.0, 0.14)
    return np.clip(corrected_rgb + high * texture_alpha, 0.0, 255.0)


def integrate_faceswap(target_raw: bytes, swapped_raw: bytes, log: Any | None = None) -> tuple[bytes, QualityStats]:
    """Integrate a completed PiAPI result into the original target photo.

    Returns ``(jpeg_bytes, stats)``. The raw provider result is returned unchanged
    when the quality mask cannot be isolated safely.
    """
    import numpy as np  # type: ignore
    from PIL import Image

    target_img = _pil(target_raw)
    swapped_img = _pil(swapped_raw)
    if swapped_img.size != target_img.size:
        # PiAPI normally preserves geometry. If it does not, align only for analysis
        # and blending; never resize the untouched target itself.
        swapped_img = swapped_img.resize(target_img.size, Image.LANCZOS)

    target = np.asarray(target_img, dtype=np.uint8)
    swapped = np.asarray(swapped_img, dtype=np.uint8)
    alpha, stats = _largest_change_mask(target, swapped)
    if alpha is None:
        if callable(log):
            log("FACE_SWAP_V252_QUALITY_SKIP version=%s reason=%s changed_ratio=%.4f", VERSION, stats.reason, stats.changed_ratio)
        return bytes(swapped_raw), stats

    corrected = _lighting_match(target, swapped, alpha)
    corrected = _restore_texture(target, corrected, alpha)
    a = alpha[..., None].astype(np.float32)
    final = np.clip(target.astype(np.float32) * (1.0 - a) + corrected * a, 0.0, 255.0).astype(np.uint8)
    output = _jpeg(Image.fromarray(final, mode="RGB"), quality=96)

    if callable(log):
        log(
            "FACE_SWAP_V252_QUALITY_OK version=%s changed_ratio=%.4f bbox=%s threshold=%.2f bytes=%s",
            VERSION, stats.changed_ratio, stats.bbox, stats.threshold, len(output),
        )
    return output, stats


__all__ = ["VERSION", "QualityStats", "integrate_faceswap"]
