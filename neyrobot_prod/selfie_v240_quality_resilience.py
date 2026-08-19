# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

Historical V240-V245 entrypoints are superseded by V246. Importing this module
installs the V246 hard lock, which keeps the proven V245/V242 front-camera +
real isolated FaceSwap architecture and changes only final pixel preservation,
actual-boundary acknowledgement/duplicate protection, and Telegram timeout UX.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v246_quality_hardlock import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
