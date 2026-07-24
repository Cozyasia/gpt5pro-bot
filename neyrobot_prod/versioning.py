# -*- coding: utf-8 -*-
"""Canonical Telegram /version owner for Neyro-Bot releases.

The legacy monolith and historical runtime overlays may still expose their own
``PATCH_VERSION`` attributes.  The public /version command must not depend on
which background patch happened to write that mutable attribute last.
"""
from __future__ import annotations

from typing import Any

from . import VERSION

VERSION_HANDLER_GROUP = -1000
_VERSION_BUILDER_HOOKED = False


async def command(update: Any, context: Any) -> None:
    """Return the package release version and stop lower-priority handlers."""
    from telegram.ext import ApplicationHandlerStop

    try:
        message = getattr(update, "effective_message", None)
        if message is not None:
            await message.reply_text(
                f"✅ Код запущен: {VERSION}\n"
                "Файл должен быть именно main.py на Render. Start Command: python -u main.py"
            )
    finally:
        # Prevent the legacy main.py /version handler from replying with a stale
        # PATCH_VERSION after this canonical handler has already answered.
        raise ApplicationHandlerStop


def install_builder_hook() -> bool:
    """Install exactly one highest-priority /version handler."""
    global _VERSION_BUILDER_HOOKED
    if _VERSION_BUILDER_HOOKED:
        return True

    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return False

    class_flag = "_neyrobot_canonical_version_hooked"
    app_flag = "_neyrobot_canonical_version_handler"
    if getattr(ApplicationBuilder, class_flag, False):
        _VERSION_BUILDER_HOOKED = True
        return True

    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, app_flag, False):
            app.add_handler(
                CommandHandler("version", command),
                group=VERSION_HANDLER_GROUP,
            )
            setattr(app, app_flag, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, class_flag, True)
    _VERSION_BUILDER_HOOKED = True
    return True


__all__ = ["VERSION", "VERSION_HANDLER_GROUP", "command", "install_builder_hook"]
