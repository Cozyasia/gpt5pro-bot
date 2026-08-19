# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

V240/V241 are superseded by V242. Importing/installing this module now installs
the authoritative V242 source-expression-lock selfie runtime, so the existing
sitecustomize hook continues to work without introducing another generation owner.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v242_expression_lock import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
