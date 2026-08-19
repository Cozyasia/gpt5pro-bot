# -*- coding: utf-8 -*-
"""Compatibility entrypoint retained for sitecustomize.

V240/V241/V242 are superseded by V243. Importing/installing this module now
installs the authoritative V243 quality overlay, which preserves the proven
V242 source-expression route and adds source-guided PERSON-A facial detail
restoration without introducing another generation owner.
"""
from __future__ import annotations

from neyrobot_prod.selfie_v243_face_detail_restore import VERSION, enforce_runtime, install

__all__ = ["VERSION", "install", "enforce_runtime"]
