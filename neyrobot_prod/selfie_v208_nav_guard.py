# -*- coding: utf-8 -*-
"""Clear V208 selfie state before ordinary inline mode navigation."""
from __future__ import annotations

from typing import Any

_INSTALLED = False


async def clear_before_mode_callback(update: Any, context: Any) -> None:
    from neyrobot_prod import selfie_v208_overlay as v208
    data = str(getattr(getattr(update, "callback_query", None), "data", "") or "")
    if not data.startswith("mode:"):
        return
    v208._clear(context, keep_photos=False)
    # Do not stop propagation: the existing main.py mode callback must render the menu.


def install_builder_hook() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
    except Exception:
        return False
    original = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original(self, *args, **kwargs)
        if not getattr(app, "_selfie_v208_nav_guard", False):
            app.add_handler(
                CallbackQueryHandler(clear_before_mode_callback, pattern=r"^mode:(?:root|study|work|fun|medicine)$"),
                group=-1689,
            )
            setattr(app, "_selfie_v208_nav_guard", True)
        return app

    ApplicationBuilder.build = build
    _INSTALLED = True
    return True


__all__ = ["clear_before_mode_callback", "install_builder_hook"]
