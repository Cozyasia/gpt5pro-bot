# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

Historical V240/V241/V242/V243/V244 entrypoints are superseded by V245.
The active V245 implementation currently lives in ``selfie_v244_runtime_lock``
for compatibility with older bootstrap code. Importing this module therefore
installs that V245 runtime explicitly.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v244_runtime_lock import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
