# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

V240 is superseded by V241. Importing/installing this module now installs the
late-bound authoritative V241 selfie runtime, so the existing sitecustomize hook
continues to work without introducing another generation owner.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v241_authoritative_runtime import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
