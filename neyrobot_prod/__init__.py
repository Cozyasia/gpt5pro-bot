# -*- coding: utf-8 -*-
"""Neyro-Bot production package."""

VERSION = "v239-star-selfie-v232-scene-terminal-user-faceswap-2026-08-02"

try:
    from .star_selfie.bootstrap import install_builder_hook as _install_star_selfie_builder_hook
    _install_star_selfie_builder_hook()
except Exception:
    # Star Selfie is optional and must never block production startup.
    pass

__all__ = ["VERSION"]
