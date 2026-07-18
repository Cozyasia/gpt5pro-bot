# -*- coding: utf-8 -*-
"""Bridge the legacy photo-workshop AI-selfie button into the v123 wizard."""
from __future__ import annotations

import contextlib
from typing import Any

import celebrity_selfie_v123 as flow

VERSION = "v123.1-celebrity-selfie-photo-entry-2026-07-19"
_BUILDER_FLAG = "_celebrity_selfie_v123_pedit_builder"
_HANDLER_FLAG = "_celebrity_selfie_v123_pedit_handlers"


async def _pedit_entry(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    query = update.callback_query
    data = str(getattr(query, "data", "") or "")
    if data != "pedit:aiselfie":
        return
    with contextlib.suppress(Exception):
        await query.answer()
    # This route used to open the legacy name-only Comet prompt. It now opens
    # exactly the same exclusive wizard as the Entertainment menu entry.
    await flow._open_entry(update, context)
    raise ApplicationHandlerStop


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(
                CallbackQueryHandler(_pedit_entry, pattern=r"^pedit:aiselfie$"),
                group=-10001,
            )
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = ["VERSION", "install_builder_hook"]
