# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

Historical V240/V241/V242/V243/V244 entrypoints are superseded by V245.
Importing this module now installs the V245 clean real-FaceSwap runtime, which
keeps the proven V242 front-camera/expression contract, isolated real FaceSwap,
and adds only the compact native-resolution ROI, clean target-only merge,
immediate scene acknowledgement and duplicate-generation guard.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v245_clean_faceswap import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
