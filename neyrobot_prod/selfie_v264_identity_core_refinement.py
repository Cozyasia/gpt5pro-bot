# -*- coding: utf-8 -*-
"""Bounded identity-core refinement for the V264 strict candidate.

This overlay does not add a third attempt and does not change Telegram routing. The
standard V264 candidate is byte-for-byte delegated to the accepted production
compositor. Only the already-existing strict retry receives a compact, soft-edged
source-identity correction inside PERSON-A's anatomical face mask.

The correction restores a bounded amount of source low-frequency identity signal that
Poisson integration can otherwise wash out. It is LAB-matched to the generated scene,
kept away from the mask boundary, clipped per channel, and followed by V264's existing
MobileFace+dense-landmark candidate selection. If it does not improve identity while
remaining geometrically safe, the standard candidate is retained.
"""
from __future__ import annotations

from typing import Any, Callable

from neyrobot_prod import selfie_v264_dense68_roi_production as v264

VERSION = v264.VERSION
_INSTALLED = False
_BASE_COMPOSE: Callable[..., Any] | None = None

_CORE_LARGE_FACE_MIN = 500.0
_CORE_LOW_STRENGTH_LARGE = 0.52
_CORE_LOW_STRENGTH_MEDIUM = 0.44
_CORE_PIXEL_MIX_LARGE = 0.10
_CORE_PIXEL_MIX_MEDIUM = 0.08
_CORE_DELTA_LIMIT = 34.0
_CORE_SIGMA_FRACTION = 0.014
_CORE_SIGMA_MIN = 5.0
_CORE_SIGMA_MAX = 11.0
_CORE_BOUNDARY_START = 0.55
_CORE_BOUNDARY_SPAN = 1.75


def _log(message: str, *args: Any) -> None:
    v264._log(message, *args)


def _identity_core_strength(face_min: float) -> tuple[float, float]:
    if float(face_min) >= _CORE_LARGE_FACE_MIN:
        return _CORE_LOW_STRENGTH_LARGE, _CORE_PIXEL_MIX_LARGE
    return _CORE_LOW_STRENGTH_MEDIUM, _CORE_PIXEL_MIX_MEDIUM


def _inject_bounded_identity_core(
    composed_roi,
    corrected_roi,
    target_roi,
    mask_roi,
    face_min: float,
    boundary: float,
):
    """Restore bounded source identity only in the deep inner-face ROI.

    The boundary ring stays exactly as produced by the accepted V264 compositor.
    This prevents the high-similarity candidate from winning by creating a pasted
    face edge or changing PERSON-B/background pixels.
    """
    import cv2
    import numpy as np

    composed = np.asarray(composed_roi, dtype=np.uint8)
    matched = v264._colour_match_lab_roi_only(corrected_roi, target_roi, mask_roi)
    binary = (np.asarray(mask_roi) > 80).astype(np.uint8)
    if int(binary.sum()) < 500:
        return composed.copy(), 0.0, 0.0, 0.0, 0.0

    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5).astype(np.float32)
    start = max(6.0, float(boundary) * _CORE_BOUNDARY_START)
    span = max(14.0, float(boundary) * _CORE_BOUNDARY_SPAN)
    normalized = np.clip((distance - start) / max(1.0, span), 0.0, 1.0)
    core_alpha = v264.v262._smoothstep01(normalized).astype(np.float32) * binary.astype(np.float32)

    low_strength, pixel_mix = _identity_core_strength(face_min)
    sigma = max(_CORE_SIGMA_MIN, min(_CORE_SIGMA_MAX, float(face_min) * _CORE_SIGMA_FRACTION))

    source_float = matched.astype(np.float32)
    current_float = composed.astype(np.float32)
    source_low = cv2.GaussianBlur(source_float, (0, 0), sigmaX=sigma, sigmaY=sigma)
    current_low = cv2.GaussianBlur(current_float, (0, 0), sigmaX=sigma, sigmaY=sigma)
    low_delta = np.clip(source_low - current_low, -_CORE_DELTA_LIMIT, _CORE_DELTA_LIMIT)

    alpha3 = core_alpha[:, :, None]
    refined = current_float + low_delta * (alpha3 * float(low_strength))
    # A small full-spectrum matched-source component helps MobileFace retain iris,
    # brow and lip identity without moving any geometry. It is restricted to the
    # same deep core and therefore cannot create a boundary seam.
    mix = alpha3 * float(pixel_mix)
    refined = refined * (1.0 - mix) + source_float * mix
    refined = np.clip(refined, 0.0, 255.0).astype(np.uint8)

    # Exact pixel lock outside the anatomical mask is non-negotiable.
    refined[binary == 0] = composed[binary == 0]
    return refined, float(low_strength), float(pixel_mix), float(sigma), float(core_alpha.max())


def _identity_core_compose_roi(corrected_roi, target_roi, mask_roi, face_min: float, *, strict: bool):
    if _BASE_COMPOSE is None:
        raise RuntimeError("V264 identity-core base compositor is not installed")

    composed, blend_mode, boundary, structure_strength, detail_strength = _BASE_COMPOSE(
        corrected_roi, target_roi, mask_roi, face_min, strict=strict
    )
    if not strict:
        return composed, blend_mode, boundary, structure_strength, detail_strength

    refined, low_strength, pixel_mix, sigma, max_alpha = _inject_bounded_identity_core(
        composed, corrected_roi, target_roi, mask_roi, face_min, boundary
    )
    _log(
        "AI_SELFIE_V264_IDENTITY_CORE status=applied strict=true roi_only=true "
        "source_low_frequency=bounded deep_core_only=true boundary_pixel_lock=true "
        "low_strength=%.2f pixel_mix=%.2f sigma=%.2f delta_limit=%.1f max_alpha=%.3f",
        low_strength, pixel_mix, sigma, _CORE_DELTA_LIMIT, max_alpha,
    )
    return (
        refined,
        f"{blend_mode}+bounded_source_identity_core",
        boundary,
        structure_strength,
        detail_strength,
    )


def install() -> None:
    global _INSTALLED, _BASE_COMPOSE
    if _INSTALLED:
        if v264._structure_first_compose_roi is not _identity_core_compose_roi:
            v264._structure_first_compose_roi = _identity_core_compose_roi
        return

    current = v264._structure_first_compose_roi
    if current is _identity_core_compose_roi:
        _INSTALLED = True
        return
    _BASE_COMPOSE = current
    v264._structure_first_compose_roi = _identity_core_compose_roi
    _INSTALLED = True
    _log(
        "AI_SELFIE_V264_IDENTITY_CORE_INSTALL status=ok strict_candidate=bounded_source_identity_core "
        "standard_unchanged=true max_attempts=2 roi_only=true person_b=pixel_locked"
    )


__all__ = [
    "VERSION",
    "install",
    "_inject_bounded_identity_core",
    "_identity_core_compose_roi",
    "_identity_core_strength",
]
