"""Telegram wizard for paid multi-scene real-estate video reviews."""
from __future__ import annotations

import os
import tempfile
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
SOUND_LABELS = {
    "none": "Без звука",
    "music": "Фоновая музыка Suno",
    "voice": "Диктор",
    "both": "Диктор + музыка",
}
VOICE_LABELS = {"male": "Спокойный мужской", "female": "Мягкий женский"}
LANGUAGE_LABELS = {"ru": "Русский", "en": "English"}
RenderCallback = Callable[[str, list[str], str, str, int], Awaitable[str]]
_renderer: RenderCallback | None = None


def menu_button():
    return InlineKeyboardButton("🏡 AI-видеообзор недвижимости", callback_data=PREFIX + "start")


def keyboard(rows):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=PREFIX + value) for label, value in row]
        for row in rows
    ])


def _price_quote_key(state: dict) -> str:
    return "|".join(str(value) for value in (
        state.get("type"), len(state.get("photos") or []), state.get("aspect", "auto"),
        state.get("engine"), state.get("duration"), state.get("sound_mode", "none"),
        state.get("narration_language", ""), state.get("narration_voice", ""),
    ))


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
        await query.message.reply_text(
            "Выберите звуковое оформление:",
            reply_markup=keyboard([
                [("🎙 Диктор + музыка", "sound:both")],
                [("🎵 Фоновая музыка", "sound:music"), ("🎙 Только диктор", "sound:voice")],
                [("🔇 Без звука", "sound:none")],
            ]),
        )
    elif action.startswith("sound:"):
        sound_mode = action.split(":", 1)[1]
        if sound_mode not in SOUND_LABELS:
            await query.message.reply_text("Неизвестный режим звука.")
            return
        state["sound_mode"] = sound_mode
        state.pop("narration_plan", None)
        state.pop("reference_analysis", None)
        if sound_mode in {"voice", "both"}:
            await query.message.reply_text(
                "Выберите язык диктора:",
                reply_markup=keyboard([[("🇷🇺 Русский", "language:ru"), ("🇬🇧 English", "language:en")]]),
            )
        else:
            await _ask_shooting_prompt(query.message, state)
    elif action.startswith("language:"):
        language = action.split(":", 1)[1]
        if language not in LANGUAGE_LABELS:
            await query.message.reply_text("Неизвестный язык.")
            return
        state["narration_language"] = language
        await query.message.reply_text(
            "Выберите голос диктора:",
            reply_markup=keyboard([
                [("🎙 Спокойный мужской", "voice:male")],
                [("🎙 Мягкий женский", "voice:female")],
            ]),
        )
    elif action.startswith("voice:"):
        voice = action.split(":", 1)[1]
        if voice not in VOICE_LABELS:
            await query.message.reply_text("Неизвестный голос.")
            return
        state["narration_voice"] = voice
        await _ask_shooting_prompt(query.message, state)
    elif action == "default_prompt":
        state["extra"] = ""
        state["awaiting_prompt"] = False
        await confirm(query.message, state, context, query.from_user.id, query.message.chat_id)
    elif action == "narration_edit":
        state["awaiting_narration_script"] = True
        await query.message.reply_text(
            "Пришлите новый текст диктора. Лучше написать отдельную строку для каждой сцены. "
            "Бот автоматически ограничит длину текста таймингом ролика."
        )
    elif action == "recover":
        from property_video_execution import recover_ready
        await recover_ready(update, context)
    elif action == "confirm_paid":
        if not state.get("price_confirmed") or state.get("price_quote_key") != _price_quote_key(state):
            state["price_confirmed"] = False
            await query.message.reply_text(
                "Настройки изменились после расчёта. Нажмите «Создать видео», чтобы увидеть и подтвердить актуальную стоимость."
            )
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
            quote = quote_for_job(
                state["engine"], len(state["photos"]), state["duration"], state["type"],
                sound_mode=state.get("sound_mode", "none"),
            )
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
        state["price_quote_key"] = _price_quote_key(state)
        audio_cost = float(quote.get("music_cost_usd", 0)) + float(quote.get("voice_cost_usd", 0))
        breakdown = (
            f"Видео API: примерно ${quote.get('video_cost_usd', quote['provider_cost_usd']):.2f}"
            + (f" · аудио API: примерно ${audio_cost:.2f}" if audio_cost else "")
        )
        if owner_free:
            await query.message.reply_text(
                f"🧪 Тестовый доступ владельца\n"
                f"Провайдер: {ENGINES[state['engine']]} · сцен: {quote['scene_count']}\n"
                f"{breakdown}\nВсего API: примерно ${quote['provider_cost_usd']:.2f}\n"
                "С внутреннего баланса пользователя списания не будет. Запустить реальную генерацию?",
                reply_markup=keyboard([[('🧪 Запустить тест без списания', 'confirm_paid')], [('↩️ Отмена', 'start')]]),
            )
            return
        await query.message.reply_text(
            f"💳 Стоимость обзора: ${quote['retail_usd']:.2f}{credits}\n"
            f"Сцен: {quote['scene_count']} · Провайдер: {ENGINES[state['engine']]}\n"
            f"{breakdown}\n"
            "Сумма резервируется перед запуском и списывается только после доставки MP4. Подтвердить?",
            reply_markup=keyboard([[("💳 Подтверждаю оплату", "confirm_paid")], [("↩️ Отмена", "start")]]),
        )


async def _ask_shooting_prompt(message, state):
    state["awaiting_prompt"] = True
    await message.reply_text(
        "Напишите дополнительные пожелания к съёмке или нажмите «Готовый промпт».",
        reply_markup=keyboard([[("✨ Готовый промпт", "default_prompt")]]),
    )


async def _prepare_narration(message, state, context, user_id: int, chat_id: int):
    if state.get("sound_mode") not in {"voice", "both"} or state.get("narration_plan"):
        return
    await message.reply_text("📝 Анализирую фотографии и готовлю синхронный текст диктора…")
    from property_video_director import analyse_reference_photos
    from property_video_pipeline import plan_property_scenes
    from property_video_audio import create_narration_plan
    from real_estate_pipeline import fetch_telegram_photos
    with tempfile.TemporaryDirectory(prefix="property_narration_") as folder:
        paths = await fetch_telegram_photos(context.bot, list(state.get("photos") or []), folder)
        analysis = await analyse_reference_photos(paths)
    labels = [str(item.get("space") or "unknown") for item in analysis]
    scenes = plan_property_scenes(
        len(analysis), int(state["duration"]), state["engine"], state["type"], labels=labels,
    )
    state["reference_analysis"] = analysis
    state["narration_plan"] = await create_narration_plan(
        analysis, scenes,
        state.get("narration_language", "ru"), state.get("narration_voice", "female"),
        user_id=user_id, chat_id=chat_id,
    )


async def confirm(message, state, context, user_id: int, chat_id: int):
    try:
        await _prepare_narration(message, state, context, user_id, chat_id)
    except Exception as exc:
        state.pop("narration_plan", None)
        state.pop("reference_analysis", None)
        await message.reply_text(
            f"Не удалось подготовить текст диктора: {str(exc)[:300]}. Выберите другой режим звука или попробуйте снова."
        )
        return
    prompt = PROMPTS[state["type"]] + ("\n" + state.get("extra", "") if state.get("extra") else "")
    plan = state.get("narration_plan") or {}
    if plan.get("segments"):
        lines = [f"{item['start']:g} сек. — {item['text']}" for item in plan["segments"]]
        await message.reply_text("🎙 Текст диктора:\n\n" + "\n".join(lines))
    rows = [[("🚀 Создать видео", "generate")]]
    if plan.get("segments"):
        rows.append([("✏️ Изменить текст диктора", "narration_edit")])
    rows.append([("↩️ Заново", "start")])
    await message.reply_text(
        f"🎬 {state['type']} | {ENGINES[state['engine']]} | {state['duration']} сек.\n"
        f"Фото: {len(state['photos'])} · формат: {state.get('aspect', 'auto')}\n"
        f"Звук: {SOUND_LABELS.get(state.get('sound_mode', 'none'), 'Без звука')}\n\n"
        f"Промпт:\n{prompt[:1800]}",
        reply_markup=keyboard(rows),
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
    if not state or not state.get("engine"):
        return
    if state.get("awaiting_narration_script"):
        from property_video_audio import manual_narration_plan
        from property_video_pipeline import plan_property_scenes
        analysis = list(state.get("reference_analysis") or [])
        labels = [str(item.get("space") or "unknown") for item in analysis]
        scenes = plan_property_scenes(
            len(state.get("photos") or []), int(state["duration"]), state["engine"], state["type"],
            labels=labels if len(labels) == len(state.get("photos") or []) else None,
        )
        try:
            state["narration_plan"] = manual_narration_plan(
                update.message.text[:2500], scenes,
                state.get("narration_language", "ru"), state.get("narration_voice", "female"),
            )
        except ValueError as exc:
            await update.message.reply_text(f"Не удалось распределить текст по сценам: {exc}")
            return
        state["awaiting_narration_script"] = False
        await confirm(update.message, state, context, update.effective_user.id, update.effective_chat.id)
        return
    if not state.get("awaiting_prompt"):
        return
    state["extra"] = update.message.text[:1500]
    state["awaiting_prompt"] = False
    await confirm(update.message, state, context, update.effective_user.id, update.effective_chat.id)


def register_real_estate_handlers(application, renderer: RenderCallback | None = None):
    global _renderer
    _renderer = renderer
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^revideo:"), group=1)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo), group=-1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, custom_prompt), group=-1)
