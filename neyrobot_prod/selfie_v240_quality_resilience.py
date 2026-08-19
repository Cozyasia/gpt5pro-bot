# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

Historical V240/V241/V242/V243 entrypoints are superseded by V244. Importing
this module now installs the final V244 runtime lock, which preserves V243's
real FaceSwap/detail route and prevents older builder wrappers from taking
ownership again after startup.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v244_runtime_lock import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
