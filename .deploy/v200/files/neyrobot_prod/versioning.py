# -*- coding: utf-8 -*-
"""Canonical production version contract.

This module deliberately does not install Telegram handlers, overwrite
``PATCH_VERSION`` in a background thread, or load historical Celebrity Selfie
releases. ``main.py`` owns /version and registers the clean selfie feature.
"""
from __future__ import annotations

VERSION = "v200-celebrity-selfie-clean-rewrite-2026-07-24"
_INSTALLED = False


def install_early() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
    except Exception:
        pass
    _INSTALLED = True


__all__ = ["install_early", "VERSION"]
