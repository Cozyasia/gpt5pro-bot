# -*- coding: utf-8 -*-
"""Production bootstrap with Celebrity Selfie fully disabled.

This release intentionally removes the public Celebrity Selfie / AI-photo-with-a-
hero mode. No selfie catalogue, admin, provider, callback, photo or text handlers
are installed from this bootstrap. Legacy callback payloads are intercepted and
stopped so an old Telegram button cannot reach historical handlers.
"""
from __future__ import annotations

import contextlib

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from telegram.ext import ApplicationBuilder, ApplicationHandlerStop, CallbackQueryHandler

    REMOVED_VERSION = "v237-celebrity-selfie-removed-2026-07-29"
    _builder_flag = "_neyrobot_selfie_removed_builder_hooked"

    async def _removed_selfie_callback(update, context):
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        with contextlib.suppress(Exception):
            await query.answer("Режим удалён", show_alert=False)
        message = getattr(query, "message", None)
        if message is not None:
            await message.reply_text(
                "🗑 Режим «Селфи со звездой» полностью удалён и сейчас недоступен. "
                "Старые кнопки больше не запускают генерацию."
            )
        print(f"CELEBRITY_SELFIE_REMOVED_BLOCK callback={getattr(query, 'data', '')}", flush=True)
        raise ApplicationHandlerStop

    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_without_selfie(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            app.add_handler(
                CallbackQueryHandler(
                    _removed_selfie_callback,
                    pattern=r"^(cs20[0-9]:|cs21[0-9]:|cs22[0-9]:|cs23[0-9]:|act:fun:aiselfie|fun:aiselfie|act:fun:as_preset_)"
                ),
                group=-100000,
            )
            setattr(app, "_neyrobot_celebrity_selfie_removed", True)
            return app

        ApplicationBuilder.build = _build_without_selfie
        setattr(ApplicationBuilder, _builder_flag, True)

    print("[neyrobot-prod] Celebrity Selfie mode REMOVED; legacy callbacks blocked", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] selfie removal guard warning: {type(exc).__name__}: {exc}", flush=True)
