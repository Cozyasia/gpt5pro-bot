"""Telegram wizard for paid multi-scene real-estate video reviews."""
from __future__ import annotations

import os
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, MessageHandler, ContextTypes, filters

PREFIX = "revideo:"
PROMPTS = {
    "exterior": (
        "Professional photorealistic luxury real-estate exterior walkthrough. Use the uploaded "
        "photos as strict architectural references. Smooth gimbal dolly-in, subtle lateral "
        "parallax, natural tropical daylight, realistic pool reflections. Preserve roof, "
        "facade, windows, doors, landscaping and proportions. Never invent structural details. "
        "No morphing, warping, or text."
    ),
    "interior": (
        "Professional photorealistic interior property tour based on the supplied photographs. "
        "Slow stabilized walking camera, preserve consistent lighting, materials, furniture and "
        "room geometry. Sequence rooms in upload order. Never invent additional bedrooms, "
        "amenities, doors or a floor plan. No object morphing or warped walls."
    ),
    "full": (
        "Premium real-estate film combining an exterior establishing shot and a smooth interior "
        "tour. Preserve all photographed architectural features and furniture. Use the first "
        "supplied exterior view as the establishing shot, then follow the remaining supplied "
        "views in order. Do not assert an unverified floor plan. No invented amenities or geometry changes."
    ),
}
ENGINES = {"kling": "Kling", "veo": "Google Veo", "seedance": "Seedance"}
RenderCallback = Callable[[str, list[str], str, str, int], Awaitable[str]]
_renderer: RenderCallback | None = None


def menu_button():
    return InlineKeyboardButton("🏡 AI-видеообзор недвижимости", callback_data=PREFIX + "start")


def keyboard(rows):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=PREFIX + value) for label, value in row]
        for row in rows
    ])


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data[len(PREFIX):]
    state = context.user_data.setdefault("real_estate_video", {})
    if action == "start":
        state.clear()
        await query.message.reply_text(
            "🏡 Видеообзор недвижимости\nВыберите сценарий:",
            reply_markup=keyboard([
                [("🏝 Экстерьер", "type:exterior")],
                [("🛋 Интерьер", "type:interior")],
                [("🎬 Полный обзор", "type:full")],
            ]),
        )
    elif action.startswith("type:"):
        state["type"] = action.split(":", 1)[1]
        state["photos"] = []
        await query.message.reply_text(
            "Пришлите фотографии объекта по порядку (до 10). Для интерьера загружайте комнаты "
            "в желаемом порядке обхода. Затем нажмите «Фото загружены».",
            reply_markup=keyboard([[("✅ Фото загружены", "photos_done")]]),
        )
    elif action == "photos_done":
        if not state.get("photos"):
            await query.message.reply_text("Сначала загрузите хотя бы одну фотографию.")
            return
        await query.message.reply_text(
            f"Получено фотографий: {len(state['photos'])}. Выберите движок:",
            reply_markup=keyboard([[("Kling", "engine:kling")], [("Google Veo", "engine:veo")], [("Seedance", "engine:seedance")]]),
        )
    elif action.startswith("engine:"):
        engine = action.split(":", 1)[1]
        if engine not in ENGINES:
            await query.message.reply_text("Неизвестный движок.")
            return
        state["engine"] = engine
        await query.message.reply_text(
            "Выберите длительность:",
            reply_markup=keyboard([
                [("8 секунд", "duration:8")],
                [("10 секунд", "duration:10"), ("20 секунд", "duration:20")],
                [("30 секунд", "duration:30")],
            ]),
        )
    elif action.startswith("duration:"):
        duration = int(action.split(":", 1)[1])
        if duration not in (8, 10, 20, 30):
            await query.message.reply_text("Недопустимая длительность.")
            return
        state["duration"] = duration
        state["awaiting_prompt"] = True
        await query.message.reply_text(
            "Напишите дополнительные пожелания к съёмке или нажмите «Готовый промпт».",
            reply_markup=keyboard([[("✨ Готовый промпт", "default_prompt")]]),
        )
    elif action == "default_prompt":
        state["extra"] = ""
        state["awaiting_prompt"] = False
        await confirm(query, state)
    elif action == "confirm_paid":
        if not state.get("price_confirmed"):
            await query.message.reply_text("Подтверждение стоимости отсутствует.")
            return
        from property_video_execution import execute
        await execute(update, context, state, PROMPTS[state["type"]] + "\n" + state.get("extra", ""))
    elif action == "generate":
        if state.get("generating"):
            await query.message.reply_text("Генерация уже запущена.")
            return
        if not all(k in state for k in ("type", "photos", "engine", "duration")) or not state["photos"]:
            await query.message.reply_text("Сессия неполная. Начните заново.")
            return
        if os.getenv("PROPERTY_VIDEO_PAID_ENABLED", "0").lower() not in ("1", "true", "yes", "on"):
            await query.message.reply_text("Платный режим видеообзора выключен в production ENV. Списаний нет.")
            return
        try:
            from property_video_execution import quote_for_job
            quote = quote_for_job(state["engine"], len(state["photos"]), state["duration"], state["type"])
        except Exception as exc:
            await query.message.reply_text(f"Не удалось рассчитать стоимость; генерация не запущена. {str(exc)[:300]}")
            return
        credits = ""
        try:
            import main as production_main
            formatter = getattr(production_main, "_credits_fmt_from_usd", None)
            if callable(formatter):
                credits = f" ({formatter(quote['retail_usd'])})"
        except Exception:
            pass
        state["quoted_price_usd"] = float(quote["retail_usd"])
        state["price_confirmed"] = True
        await query.message.reply_text(
            f"💳 Стоимость обзора: ${quote['retail_usd']:.2f}{credits}\n"
            f"Сцен: {quote['scene_count']} · Провайдер: {ENGINES[state['engine']]}\n"
            "Сумма резервируется перед запуском и списывается только после доставки MP4. Подтвердить?",
            reply_markup=keyboard([[("💳 Подтверждаю оплату", "confirm_paid")], [("↩️ Отмена", "start")]]),
        )


async def confirm(query, state):
    prompt = PROMPTS[state["type"]] + ("\n" + state.get("extra", "") if state.get("extra") else "")
    await query.message.reply_text(
        f"🎬 {state['type']} | {ENGINES[state['engine']]} | {state['duration']} сек.\n"
        f"Фото: {len(state['photos'])}\n\nПромпт:\n{prompt[:2200]}",
        reply_markup=keyboard([[("🚀 Создать видео", "generate")], [("↩️ Заново", "start")]]),
    )


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("real_estate_video")
    if not state or "photos" not in state or state.get("engine"):
        return
    if len(state["photos"]) >= 10:
        await update.message.reply_text("Максимум 10 фотографий.")
        return
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        file_id = update.message.document.file_id
    else:
        return
    if file_id not in state["photos"]:
        state["photos"].append(file_id)
    await update.message.reply_text(f"📸 Загружено: {len(state['photos'])}/10")


async def custom_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("real_estate_video")
    if not state or not state.get("awaiting_prompt") or not state.get("engine"):
        return
    state["extra"] = update.message.text[:1500]
    state["awaiting_prompt"] = False
    await update.message.reply_text(
        f"Дополнительные пожелания сохранены. Режим: {state['type']}, движок: {ENGINES[state['engine']]}.",
        reply_markup=keyboard([[("🚀 Создать видео", "generate")], [("↩️ Заново", "start")]]),
    )


def register_real_estate_handlers(application, renderer: RenderCallback | None = None):
    global _renderer
    _renderer = renderer
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^revideo:"), group=1)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo), group=-1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, custom_prompt), group=-1)
