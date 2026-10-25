"""Telegram wizard for paid multi-scene real-estate video reviews."""
from __future__ import annotations

import os
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, MessageHandler, ContextTypes, filters

PREFIX = "revideo:"
MAX_PHOTOS = 30
MASTER_DIRECTOR_PROMPT = (
    "Create an ultra-realistic architectural walkthrough of the exact property in the supplied references. "
    "The result must feel like authentic footage captured by a professional real-estate videographer physically "
    "walking with a stabilized camera, never like independently animated photographs. Camera height approximately "
    "1.6 metres; realistic 20-24mm full-frame architectural lens; smooth forward walking, gentle turns, natural "
    "acceleration and deceleration, subtle handheld micro-movement, real foreground-background parallax and changing "
    "perspective. Preserve the actual architecture, furniture, materials, lighting, colours, pool and landscaping. "
    "Infer connectivity only when the references support it. If a connection is unknown, use a restrained natural "
    "cinematic cut hidden by foreground occlusion instead of inventing a passage. Maintain consistent tropical daylight, "
    "exposure, white balance, reflections and material textures. NO photo slideshow. NO static zoom, Ken Burns effect, "
    "flat-image push-in, repeated forward-backward zoom, unrelated-room morphing, wall teleportation, invented architecture, "
    "furniture transformation, distorted doorway, impossible camera path, text, logo or watermark. Prefer a shorter accurate "
    "shot when genuine spatial movement would require fabricated geometry."
)
PROMPTS = {
    "exterior": MASTER_DIRECTOR_PROMPT + " Begin with a wide exterior establishing view and move continuously through only the visible facade, entrance, terrace, pool and landscaping.",
    "interior": MASTER_DIRECTOR_PROMPT + " Build a continuous-feeling interior route through the photographed rooms in upload order, using supported doorways and open-plan connections only.",
    "full": MASTER_DIRECTOR_PROMPT + " Build a logical continuous-feeling route from the strongest establishing view through the selected interior and exterior zones, ending on the best real hero view.",
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
            "🏡 AI-видеообзор недвижимости — Режиссёр\nВыберите сценарий:",
            reply_markup=keyboard([
                [("🏝 Экстерьер", "type:exterior")],
                [("🛋 Интерьер", "type:interior")],
                [("🎬 Полный обзор", "type:full")],
            ]),
        )
    elif action.startswith("type:"):
        state["type"] = action.split(":", 1)[1]
        state["photos"] = []
        state["photo_keys"] = []
        await query.message.reply_text(
            f"Пришлите фотографии объекта по порядку (до {MAX_PHOTOS}). Для интерьера загружайте комнаты "
            "в желаемом порядке обхода. Затем нажмите «Фото загружены».",
            reply_markup=keyboard([[("✅ Фото загружены", "photos_done")]]),
        )
    elif action == "photos_done":
        if not state.get("photos"):
            await query.message.reply_text("Сначала загрузите хотя бы одну фотографию.")
            return
        await query.message.reply_text(
            f"Получено фотографий: {len(state['photos'])}. Выберите формат:",
            reply_markup=keyboard([
                [("✨ Автоматически", "format:auto")],
                [("↔️ Горизонтально 16:9", "format:16:9")],
                [("↕️ Вертикально 9:16", "format:9:16")],
            ]),
        )
    elif action.startswith("format:"):
        aspect = action.split(":", 1)[1]
        if aspect not in {"auto", "16:9", "9:16"}:
            await query.message.reply_text("Неизвестный формат.")
            return
        state["aspect"] = aspect
        await query.message.reply_text(
            "Выберите движок:",
            reply_markup=keyboard([[("Kling", "engine:kling")], [("Google Veo", "engine:veo")], [("Seedance", "engine:seedance")]]),
        )
    elif action == "photos_add":
        count = len(state.get("photos") or [])
        await query.message.reply_text(
            f"📎 Добавляйте фотографии по порядку. Загружено: {count}/{MAX_PHOTOS}. "
            "После последней нажмите «Фото загружены».",
            reply_markup=keyboard([[('✅ Фото загружены', 'photos_done')]]),
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
                [("45 секунд", "duration:45"), ("60 секунд", "duration:60")],
            ]),
        )
    elif action.startswith("duration:"):
        duration = int(action.split(":", 1)[1])
        if duration not in (8, 10, 20, 30, 45, 60):
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
    elif action == "recover":
        from property_video_execution import recover_ready
        await recover_ready(update, context)
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
            from property_video_execution import is_property_video_owner_free, quote_for_job
            quote = quote_for_job(state["engine"], len(state["photos"]), state["duration"], state["type"])
            owner_free = is_property_video_owner_free(
                update.effective_user.id,
                getattr(update.effective_user, "username", None),
            )
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
        if owner_free:
            await query.message.reply_text(
                f"🧪 Тестовый доступ владельца\n"
                f"Провайдер: {ENGINES[state['engine']]} · сцен: {quote['scene_count']}\n"
                f"Расход API провайдера: примерно ${quote['provider_cost_usd']:.2f}\n"
                "С внутреннего баланса пользователя списания не будет. Запустить реальную генерацию?",
                reply_markup=keyboard([[('🧪 Запустить тест без списания', 'confirm_paid')], [('↩️ Отмена', 'start')]]),
            )
            return
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
        f"Фото: {len(state['photos'])} · формат: {state.get('aspect', 'auto')}\n\nПромпт:\n{prompt[:2200]}",
        reply_markup=keyboard([[("🚀 Создать видео", "generate")], [("↩️ Заново", "start")]]),
    )


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("real_estate_video")
    if not state or "photos" not in state or state.get("engine"):
        return
    if len(state["photos"]) >= MAX_PHOTOS:
        await update.message.reply_text(f"Максимум {MAX_PHOTOS} фотографий.")
        return
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        photo_key = getattr(update.message.photo[-1], "file_unique_id", None) or file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        file_id = update.message.document.file_id
        photo_key = getattr(update.message.document, "file_unique_id", None) or file_id
    else:
        return
    photo_keys = state.setdefault("photo_keys", [])
    if photo_key in photo_keys or file_id in state["photos"]:
        # Telegram can redeliver an album update or a photo with a new size.
        # Do not emit a second progress line for a reference that was not added.
        return
    state["photos"].append(file_id)
    photo_keys.append(photo_key)
    count = len(state["photos"])
    rows = [[("✅ Фото загружены", "photos_done")]]
    if count < MAX_PHOTOS:
        rows.append([("➕ Добавить ещё", "photos_add")])
        suffix = " Можно добавить ещё или нажать «Фото загружены»."
    else:
        suffix = " Лимит достигнут — нажмите «Фото загружены»."
    text = f"📸 Загружено: {count}/{MAX_PHOTOS}.{suffix}"
    markup = keyboard(rows)
    progress_id = state.get("progress_message_id")
    if progress_id:
        try:
            chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
            if chat_id is None:
                chat_id = getattr(update.message, "chat_id", None)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_id,
                text=text,
                reply_markup=markup,
            )
            return
        except Exception:
            state.pop("progress_message_id", None)
    sent = await update.message.reply_text(text, reply_markup=markup)
    message_id = getattr(sent, "message_id", None)
    if message_id:
        state["progress_message_id"] = message_id


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
