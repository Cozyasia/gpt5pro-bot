"""Opt-in registration bridge for the existing Telegram Application.

Call install() before ApplicationBuilder.build() (for example from sitecustomize).
Disabled unless REAL_ESTATE_VIDEO_ENABLED=1. This does not enable paid renders.
"""
from __future__ import annotations
import os


def install():
    if os.getenv("REAL_ESTATE_VIDEO_ENABLED", "0").lower() not in ("1", "true", "yes"):
        return False
    from telegram.ext import ApplicationBuilder, CommandHandler
    from real_estate_video import register_real_estate_handlers, callback

    original = ApplicationBuilder.build
    if getattr(original, "_real_estate_bridge", False):
        return True

    def wrapped(self):
        app = original(self)
        # No provider attached until credit reservation and idempotent billing
        # are integrated. The /propertyvideo command is a safe preview entrypoint.
        register_real_estate_handlers(app, renderer=None)

        async def start(update, context):
            context.user_data.setdefault("real_estate_video", {}).clear()
            await update.message.reply_text(
                "🏡 Видеообзор недвижимости: выберите режим",
                reply_markup=__import__("telegram").InlineKeyboardMarkup([[
                    __import__("telegram").InlineKeyboardButton(
                        "🏡 Создать обзор", callback_data="revideo:start"
                    )
                ]]),
            )
        app.add_handler(CommandHandler("propertyvideo", start), group=-2)
        return app

    wrapped._real_estate_bridge = True
    ApplicationBuilder.build = wrapped
    return True
