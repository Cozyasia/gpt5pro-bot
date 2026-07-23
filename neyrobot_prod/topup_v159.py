# -*- coding: utf-8 -*-
"""Priority entrypoint for the canonical v159 credit menu."""
from __future__ import annotations

import contextlib
from typing import Any

_GROUP = -50_001
_BUILDER_FLAG = "_neyrobot_topup_v159_builder"
_HANDLER_FLAG = "_neyrobot_topup_v159_handler"


async def _topup(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from . import hotfix_v159 as release

    with contextlib.suppress(Exception):
        await update.callback_query.answer()
    mod = release._runtime_module()
    if mod is None:
        await update.effective_message.reply_text("Бот ещё запускается. Повторите через несколько секунд.")
        raise ApplicationHandlerStop
    release._patch_runtime(mod)
    await release._send_topup_menu(mod, update, context)
    raise ApplicationHandlerStop


def install_early() -> None:
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
            app.add_handler(CallbackQueryHandler(_topup, pattern=r"^topup$"), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = ["install_early", "_topup"]
