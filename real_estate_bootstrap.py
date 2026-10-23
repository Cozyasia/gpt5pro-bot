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
        _patch_main_fun_menu()
        # The guarded router enters the existing Telegram application. Paid
        # execution is fail-closed behind the explicit production flag and the
        # property-video credit ledger.
        register_safe_handlers(app)

        return app

    wrapped._real_estate_bridge = True
    ApplicationBuilder.build = wrapped
    return True


def _patch_main_fun_menu():
    """Add the property button after main.py is loaded, without editing its large file."""
    try:
        import main
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        original = getattr(main, "_legacy_fun_quick_kb", None)
        if not callable(original) or getattr(original, "_property_video_menu", False):
            return

        def wrapped(*args, **kwargs):
            markup = original(*args, **kwargs)
            rows = list(getattr(markup, "inline_keyboard", ()) or ())
            if not any(
                getattr(button, "callback_data", "") == "revideo:start"
                for row in rows for button in row
            ):
                rows.insert(0, [InlineKeyboardButton("🏡 AI-видеообзор недвижимости", callback_data="revideo:start")])
            return InlineKeyboardMarkup(rows)

        wrapped._property_video_menu = True
        main._legacy_fun_quick_kb = wrapped
    except Exception:
        # Menu decoration must never prevent the existing bot from starting.
        return
