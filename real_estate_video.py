"""Real-estate video wizard for python-telegram-bot 21.x.

Register with register_real_estate_handlers(application). Provider execution is deliberately
delegated to an injected async render callback; no simulated video is returned.
"""
from __future__ import annotations

from typing import Awaitable, Callable
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, MessageHandler, ContextTypes, filters

PREFIX = "revideo:"
PROMPTS = {
    "exterior": (
        "Professional photorealistic luxury real-estate exterior walkthrough. Use the uploaded "
        "photos as strict architectural references. Smooth gimbal dolly-in, subtle lateral "
        "parallax, natural tropical daylight, realistic pool reflections. Preserve roof, "
        "facade, windows, doors, landscaping and proportions. Connect viewpoints only where "
        "visually plausible. Never invent structural details. No morphing, warping, or text."
    ),
    "interior": (
        "Professional photorealistic interior property tour based on the supplied photographs. "
        "Slow stabilized walking camera, consistent lighting, materials, furniture and room "
        "geometry. Sequence rooms in upload order. Use short neutral transitional corridors "
        "only where the layout is unknown; do not claim inferred connections are factual. "
        "Never invent additional bedrooms or amenities. No object morphing, no warped walls."
    ),
    "full": (
        "Premium real-estate film combining an exterior establishing shot and a smooth interior "
        "tour. Preserve all photographed architectural features and furniture. Build cinematic "
        "transitions between reference photos without asserting an unverified floor plan. "
        "Realistic lens, slow gimbal motion, no invented amenities, no geometry changes."
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
            "Пришлите фотографии объекта по порядку (до 10). "
            "Для интерьера загружайте комнаты в желаемом порядке обхода. "
            "Затем нажмите «Фото загружены».",
            reply_markup=keyboard([[("✅ Фото загружены", "photos_done")]]),
        )
    elif action == "photos_done":
        if not state.get("photos"):
            await query.message.reply_text("Сначала загрузите хотя бы одну фотографию.")
            return
        await query.message.reply_text(
            f"Получено фотографий: {len(state['photos'])}. Выберите движок:",
            reply_markup=keyboard([[("Kling", "engine:kling")], [("Google Veo", "engine:veo")],
                                   [("Seedance", "engine:seedance")]]),
        )
    elif action.startswith("engine:"):
        state["engine"] = action.split(":", 1)[1]
        await query.message.reply_text(
            "Выберите длительность:", reply_markup=keyboard([
                [("10 секунд", "duration:10"), ("20 секунд", "duration:20")],
                [("30 секунд", "duration:30")],
            ]),
        )
    elif action.startswith("duration:"):
        state["duration"] = int(action.split(":", 1)[1])
        state["awaiting_prompt"] = True
        await query.message.reply_text(
            "Напишите дополнительные пожелания к съёмке или нажмите «Готовый промпт».",
            reply_markup=keyboard([[("✨ Готовый промпт", "default_prompt")]]),
        )
    elif action == "default_prompt":
        state["extra"] = ""
        await confirm(query, state)
    elif action == "generate":
        if not all(k in state for k in ("type", "photos", "engine", "duration")) or not state["photos"]:
            await query.message.reply_text("Сессия неполная. Начните заново.")
            return
        if _renderer is None:
            await query.message.reply_text(
                "Генерация пока не подключена к API провайдера. "
                "Настройки сохранены; списание средств не выполнялось."
            )
            return
        prompt = PROMPTS[state["type"]] + "\n" + state.get("extra", "")
        await query.message.reply_text("⏳ Отправляю задачу на генерацию…")
        try:
            result_url = await _renderer(state["engine"], state["photos"], prompt, state["type"], state["duration"])
            await query.message.reply_video(video=result_url)
            state.clear()
        except Exception:
            await query.message.reply_text("Не удалось выполнить генерацию. Попробуйте ещё раз; проверьте логи провайдера.")


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
        state["photos"].append(update.message.photo[-1].file_id)
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        state["photos"].append(update.message.document.file_id)
    else:
        return
    await update.message.reply_text(f"📸 Загружено: {len(state['photos'])}/10")


async def custom_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("real_estate_video")
    if not state or not state.get("awaiting_prompt") or not state.get("engine"):
        return
    state["extra"] = update.message.text[:1500]
    state["awaiting_prompt"] = False
    await update.message.reply_text(
        f"Дополнительные пожелания сохранены. Режим: {state['type']}, "
        f"движок: {ENGINES[state['engine']]}.",
        reply_markup=keyboard([[("🚀 Создать видео", "generate")], [("↩️ Заново", "start")]]),
    )


def register_real_estate_handlers(application, renderer: RenderCallback | None = None):
    """Register after existing generic message handlers or in a higher-priority group.

    The renderer must resolve Telegram file IDs to downloadable URLs or bytes and
    orchestrate multiple provider clips when duration exceeds the provider limit.
    """
    global _renderer
    _renderer = renderer
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^revideo:"), group=-1)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo), group=-1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, custom_prompt), group=-1)
