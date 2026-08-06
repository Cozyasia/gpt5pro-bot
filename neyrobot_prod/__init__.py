# -*- coding: utf-8 -*-
"""Neyro-Bot production package."""

VERSION = "v243-resilient-piapi-transport-2026-08-06"

# Install resilient photo-3/source detection first. Gemini still creates scene,
# hero and body; PiAPI remains the sole terminal user-identity transfer stage.
try:
    from .selfie_v241_resilient_face_detection import install as _install_v241

    _install_v241()
except Exception as _v241_error:
    print(f"[neyrobot-prod] V241 detector bootstrap failed: {_v241_error!r}", flush=True)

# Remove the fatal generated-face gate. If OpenCV sees zero faces, or sees only
# the right-side hero, lock PERSON A by the deterministic left-side composition
# required by the generation prompt and continue to PiAPI face swap.
try:
    from .selfie_v242_nonfatal_target_lock import install as _install_v242

    _install_v242()
except Exception as _v242_error:
    print(f"[neyrobot-prod] V242 target-lock bootstrap failed: {_v242_error!r}", flush=True)

# PiAPI can intermittently return 429/5xx while creating or polling a face-swap
# task. Retry transient failures, progressively compact the two isolated crops,
# and never fall back to Gemini identity generation.
try:
    from .selfie_v243_resilient_piapi_transport import install as _install_v243

    _install_v243()
except Exception as _v243_error:
    print(f"[neyrobot-prod] V243 PiAPI transport bootstrap failed: {_v243_error!r}", flush=True)

__all__ = ["VERSION"]
