"""Isolated Telegram routing for the property-video wizard.

Only consumes photos/text when a property wizard is active. Other messages
continue through existing production handlers unchanged.
"""
from telegram.ext import (
    ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
    MessageHandler, filters,
)
from real_estate_video import callback, photo, custom_prompt


async def _photo(update, context):
    state = context.user_data.get("real_estate_video") or {}
    if "photos" not in state or state.get("engine"):
        return
    await photo(update, context)
    raise ApplicationHandlerStop


async def _text(update, context):
    state = context.user_data.get("real_estate_video") or {}
    if not (state.get("awaiting_prompt") or state.get("awaiting_narration_script")) or not state.get("engine"):
        return
    await custom_prompt(update, context)
    raise ApplicationHandlerStop


async def _callback(update, context):
    await callback(update, context)
    raise ApplicationHandlerStop


async def _start(update, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    context.user_data.pop("real_estate_video", None)
    await update.message.reply_text(
        "🏡 Видеообзор недвижимости",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Создать видеообзор", callback_data="revideo:start")
        ]]),
    )
    raise ApplicationHandlerStop


async def _recover(update, context):
    from property_video_execution import recover_ready
    await recover_ready(update, context)
    raise ApplicationHandlerStop


def register_safe_handlers(application):
    application.add_handler(CommandHandler("propertyvideo", _start), group=-3)
    application.add_handler(CommandHandler("propertyvideo_recover", _recover), group=-3)
    application.add_handler(CallbackQueryHandler(_callback, pattern=r"^revideo:"), group=-3)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, _photo), group=-3)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=-3)
