# -*- coding: utf-8 -*-
"""Neyro-Bot production package."""

VERSION = "v241-resilient-terminal-face-detection-2026-08-06"

# Install the photo-3 detector patch before the V239 owner imports V237/V238.
# The patch changes only local face acquisition. Gemini still creates scene,
# hero and body; PiAPI remains the sole terminal user-identity transfer stage.
try:
    from .selfie_v241_resilient_face_detection import install as _install_v241

    _install_v241()
except Exception as _v241_error:
    print(f"[neyrobot-prod] V241 detector bootstrap failed: {_v241_error!r}", flush=True)

__all__ = ["VERSION"]
