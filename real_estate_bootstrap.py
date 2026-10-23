"""Opt-in registration bridge for the existing Telegram Application.

Call install() before ApplicationBuilder.build() (for example from sitecustomize).
Disabled unless REAL_ESTATE_VIDEO_ENABLED=1. This does not enable paid renders.
"""
from __future__ import annotations
import os


def install():
    if os.getenv("REAL_ESTATE_VIDEO_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return False
    from telegram.ext import ApplicationBuilder
    from real_estate_safe_router import register_safe_handlers

    original = ApplicationBuilder.build
    if getattr(original, "_real_estate_bridge", False):
        return True

    def wrapped(self):
        app = original(self)
        # No provider attached until credit reservation and idempotent billing
        # are integrated. The /propertyvideo command is a safe preview entrypoint.
        register_safe_handlers(app)

        return app

    wrapped._real_estate_bridge = True
    ApplicationBuilder.build = wrapped
    return True
