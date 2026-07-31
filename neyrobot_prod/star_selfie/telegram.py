from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from .admin import is_admin
from .catalog.runtime import runtime_catalog
from .config import StarSelfieConfig
from .factory import build_pipeline
from .models import CaptureMode, GenerationRequest

_STATE_KEY = "star_selfie_flow"
_CALLBACK_PREFIX = "starselfie:"
_MENU_CALLBACKS = {"fun:star_selfie", "act:fun:star_selfie"}
_LOG = logging.getLogger("gpt-bot.star-selfie")
_SCENES = {
    "yacht": "On a luxury yacht at golden hour, premium travel atmosphere, sea and coastline in the background.",
    "premiere": "At a glamorous movie premiere on a red carpet with elegant lighting and press-wall atmosphere.",
    "restaurant": "At an upscale fine-dining restaurant, warm cinematic lighting, elegant interior and natural candid mood.",
    "stadium": "At a packed football stadium near the pitch, energetic match-day atmosphere and realistic stadium lighting.",
}


def _catalog(config: StarSelfieConfig):
    return runtime_catalog(config)


def _state(context: Any) -> dict[str, Any]:
    return context.user_data.setdefault(_STATE_KEY, {})


def _cleanup_files(state: dict[str, Any]) -> None:
    for key in ("scene_reference_path", "user_face_path", "user_body_path"):
        raw = state.get(key)
        if raw:
            with contextlib.suppress(OSError):
                Path(str(raw)).unlink()


def _clear(context: Any) -> None:
    state = context.user_data.pop(_STATE_KEY, None) or {}
    _cleanup_files(state)


def _character_keyboard(characters: list[Any]):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton(character.title, callback_data=f"{_CALLBACK_PREFIX}character:{character.slug}")]
        for character in characters
    ]
    rows.append([InlineKeyboardButton("✖️ Отмена", callback_data=f"{_CALLBACK_PREFIX}cancel")])
    return InlineKeyboardMarkup(rows)


def _mode_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Фото со стороны", callback_data=f"{_CALLBACK_PREFIX}mode:{CaptureMode.THIRD_PERSON.value}")],
        [InlineKeyboardButton("🤳 Настоящее селфи", callback_data=f"{_CALLBACK_PREFIX}mode:{CaptureMode.TRUE_PHONE_SELFIE.value}")],
        [InlineKeyboardButton("✖️ Отмена", callback_data=f"{_CALLBACK_PREFIX}cancel")],
    ])


def _scene_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛥 Яхта", callback_data=f"{_CALLBACK_PREFIX}scene:yacht")],
        [InlineKeyboardButton("🎬 Премьера", callback_data=f"{_CALLBACK_PREFIX}scene:premiere")],
        [InlineKeyboardButton("🍽 Ресторан", callback_data=f"{_CALLBACK_PREFIX}scene:restaurant")],
        [InlineKeyboardButton("⚽ Футбольный стадион", callback_data=f"{_CALLBACK_PREFIX}scene:stadium")],
        [InlineKeyboardButton("✍️ Своя сцена текстом", callback_data=f"{_CALLBACK_PREFIX}scene:custom_text")],
        [InlineKeyboardButton("🖼 Своя сцена по фото", callback_data=f"{_CALLBACK_PREFIX}scene:custom_photo")],
        [InlineKeyboardButton("✖️ Отмена", callback_data=f"{_CALLBACK_PREFIX}cancel")],
    ])


async def _ask_user_face(message: Any) -> None:
    await message.reply_text(
        "1/2 — отправьте чёткий портрет вашего лица анфас.\n"
        "Без очков, сильных теней и других людей в кадре."
    )


async def _ask_user_body(message: Any) -> None:
    await message.reply_text(
        "2/2 — теперь отправьте вашу фотографию в полный рост.\n"
        "В кадре должен быть один человек, тело полностью видно от головы до ног. "
        "Эта фотография нужна только для роста, комплекции и пропорций тела."
    )


async def start(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not config.enabled:
        await update.effective_message.reply_text("Функция «Селфи со звездой» пока отключена.")
        return
    characters = [
        item for item in _catalog(config).active()
        if config.required_character_refs <= len(item.reference_paths) <= config.max_character_refs
        and all(path.is_file() for path in item.reference_paths)
    ]
    if not characters:
        await update.effective_message.reply_text(
            "Каталог звёзд пока не готов: администратору нужно активировать героя и загрузить 3–6 референсов."
        )
        return
    _clear(context)
    _state(context)["step"] = "character"
    await update.effective_message.reply_text(
        "⭐ Выберите героя для совместного кадра:",
        reply_markup=_character_keyboard(characters),
    )


async def menu_callback(update: Any, context: Any, config: StarSelfieConfig) -> None:
    query = update.callback_query
    if query is None or (query.data or "") not in _MENU_CALLBACKS:
        return
    await query.answer("Селфи со звездой")
    await start(update, context, config)


async def callback(update: Any, context: Any, config: StarSelfieConfig) -> None:
    query = update.callback_query
    if query is None or not (query.data or "").startswith(_CALLBACK_PREFIX):
        return
    await query.answer()
    action = query.data[len(_CALLBACK_PREFIX):]
    if action == "cancel":
        _clear(context)
        await query.edit_message_text("Создание селфи отменено.")
        return

    state = _state(context)
    if action.startswith("character:"):
        slug = action.split(":", 1)[1]
        character = _catalog(config).get(slug)
        if character is None or not character.active:
            await query.edit_message_text("Этот герой сейчас недоступен. Запустите /star_selfie заново.")
            _clear(context)
            return
        state.update({"step": "mode", "character": character.slug})
        await query.edit_message_text(
            f"Вы выбрали: {character.title}\n\nКак должен выглядеть кадр?",
            reply_markup=_mode_keyboard(),
        )
        return

    if action.startswith("mode:"):
        try:
            mode = CaptureMode(action.split(":", 1)[1])
        except ValueError:
            await query.edit_message_text("Неизвестный режим. Запустите /star_selfie заново.")
            _clear(context)
            return
        if not state.get("character"):
            await query.edit_message_text("Сессия устарела. Запустите /star_selfie заново.")
            _clear(context)
            return
        state.update({"step": "scene", "mode": mode.value})
        await query.edit_message_text(
            "Выберите сцену для совместного кадра:",
            reply_markup=_scene_keyboard(),
        )
        return

    if action.startswith("scene:"):
        scene_key = action.split(":", 1)[1]
        if scene_key in _SCENES:
            state.update({"step": "face_photo", "scene": _SCENES[scene_key], "scene_key": scene_key})
            await query.edit_message_text("✅ Сцена выбрана.")
            await _ask_user_face(query.message)
            return
        if scene_key == "custom_text":
            state["step"] = "scene_text"
            await query.edit_message_text(
                "Опишите сцену одним сообщением. Например: «на крыше небоскрёба ночью, огни города, премиальный стиль»."
            )
            return
        if scene_key == "custom_photo":
            state["step"] = "scene_photo"
            await query.edit_message_text(
                "Отправьте фотографию места или композиции, которую нужно использовать как референс сцены."
            )
            return


async def text_input(update: Any, context: Any) -> None:
    state = context.user_data.get(_STATE_KEY) or {}
    if state.get("step") != "scene_text":
        return
    text = (update.effective_message.text or "").strip()
    if len(text) < 5:
        await update.effective_message.reply_text("Опишите сцену подробнее, минимум 5 символов.")
        return
    state.update({"step": "face_photo", "scene": text[:1200], "scene_key": "custom_text"})
    await update.effective_message.reply_text("✅ Своя сцена сохранена.")
    await _ask_user_face(update.effective_message)


async def _download_photo(update: Any, context: Any, path: Path) -> None:
    telegram_file = await context.bot.get_file(update.effective_message.photo[-1].file_id)
    await telegram_file.download_to_drive(custom_path=path)


async def photo(update: Any, context: Any, config: StarSelfieConfig) -> None:
    state = context.user_data.get(_STATE_KEY) or {}
    step = state.get("step")
    if step not in {"scene_photo", "face_photo", "body_photo"} or not update.effective_message.photo:
        return

    user_id = int(update.effective_user.id)
    incoming_dir = config.persistent_root / "incoming" / str(user_id)
    incoming_dir.mkdir(parents=True, exist_ok=True)

    if step == "scene_photo":
        scene_path = incoming_dir / f"scene_{update.effective_message.message_id}.jpg"
        await _download_photo(update, context, scene_path)
        state.update({
            "step": "face_photo",
            "scene": "Use the optional final reference image only as the visual composition and location reference. Preserve its environment while placing exactly the user and the selected celebrity naturally into the scene.",
            "scene_key": "custom_photo",
            "scene_reference_path": str(scene_path),
        })
        await update.effective_message.reply_text("✅ Фото сцены сохранено.")
        await _ask_user_face(update.effective_message)
        return

    if step == "face_photo":
        face_path = incoming_dir / f"face_{update.effective_message.message_id}.jpg"
        await _download_photo(update, context, face_path)
        old = state.get("user_face_path")
        if old:
            with contextlib.suppress(OSError):
                Path(str(old)).unlink()
        state.update({"step": "body_photo", "user_face_path": str(face_path)})
        await update.effective_message.reply_text("✅ Портрет лица сохранён.")
        await _ask_user_body(update.effective_message)
        return

    character = _catalog(config).get(str(state.get("character") or ""))
    if character is None or not character.active:
        _clear(context)
        await update.effective_message.reply_text("Герой больше недоступен. Запустите /star_selfie заново.")
        return

    face_path = Path(str(state.get("user_face_path") or ""))
    if not face_path.is_file():
        state["step"] = "face_photo"
        await update.effective_message.reply_text("Портрет лица потерян. Отправьте фотографию лица ещё раз.")
        return

    body_path = incoming_dir / f"body_{update.effective_message.message_id}.jpg"
    await _download_photo(update, context, body_path)
    old_body = state.get("user_body_path")
    if old_body:
        with contextlib.suppress(OSError):
            Path(str(old_body)).unlink()
    state.update({"step": "generating", "user_body_path": str(body_path)})
    progress = await update.effective_message.reply_text(
        "⏳ Создаю выбранную сцену, сохраняю ваше телосложение и переношу лицо…"
    )
    try:
        scene_reference_path = state.get("scene_reference_path")
        request = GenerationRequest(
            user_id=user_id,
            user_face_path=face_path,
            user_body_path=body_path,
            character=character,
            scene=str(state.get("scene") or "A natural premium joint portrait."),
            capture_mode=CaptureMode(str(state["mode"])),
            scene_reference_path=Path(scene_reference_path) if scene_reference_path else None,
        )
        result = await build_pipeline(config).run(request)
        with result.final_image_path.open("rb") as image:
            await update.effective_message.reply_photo(
                photo=image,
                caption=f"✅ Готово: {character.title}",
            )
        context.application.bot_data.pop("star_selfie_last_error", None)
        _clear(context)
    except Exception as exc:
        state["step"] = "body_photo"
        error_text = f"{type(exc).__name__}: {exc}"
        with contextlib.suppress(Exception):
            context.application.bot_data["star_selfie_last_error"] = error_text[:1500]
        _LOG.exception(
            "Star Selfie generation failed user_id=%s character=%s mode=%s scene=%s: %s",
            user_id, character.slug, state.get("mode"), state.get("scene_key"), error_text,
        )
        message = (
            "❌ Не удалось завершить генерацию.\n"
            "Отправьте фото в полный рост ещё раз или отмените командой /cancel_star_selfie."
        )
        if is_admin(update.effective_user):
            message += f"\n\n🔧 Техническая причина:\n{error_text[:1200]}"
        with contextlib.suppress(Exception):
            await progress.edit_text(message)


async def cancel(update: Any, context: Any) -> None:
    existed = bool(context.user_data.get(_STATE_KEY))
    _clear(context)
    await update.effective_message.reply_text(
        "Создание селфи отменено." if existed else "Активной генерации селфи нет."
    )


def register_handlers(app: Any, config: StarSelfieConfig, *, group: int = -98) -> bool:
    if not config.enabled or getattr(app, "_star_selfie_handlers", False):
        return False

    from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, MessageHandler, filters

    async def _start(update: Any, context: Any) -> None:
        await start(update, context, config)

    async def _menu_callback(update: Any, context: Any) -> None:
        await menu_callback(update, context, config)
        raise ApplicationHandlerStop

    async def _callback(update: Any, context: Any) -> None:
        await callback(update, context, config)
        raise ApplicationHandlerStop

    async def _photo(update: Any, context: Any) -> None:
        state = context.user_data.get(_STATE_KEY) or {}
        owns_photo = state.get("step") in {"scene_photo", "face_photo", "body_photo"}
        await photo(update, context, config)
        if owns_photo:
            raise ApplicationHandlerStop

    async def _text(update: Any, context: Any) -> None:
        state = context.user_data.get(_STATE_KEY) or {}
        owns_text = state.get("step") == "scene_text"
        await text_input(update, context)
        if owns_text:
            raise ApplicationHandlerStop

    app.add_handler(CommandHandler("star_selfie", _start), group=group)
    app.add_handler(CommandHandler("cancel_star_selfie", cancel), group=group)
    app.add_handler(CallbackQueryHandler(_menu_callback, pattern=r"^(?:fun:star_selfie|act:fun:star_selfie)$"), group=group)
    app.add_handler(CallbackQueryHandler(_callback, pattern=r"^starselfie:"), group=group)
    app.add_handler(MessageHandler(filters.PHOTO, _photo), group=group)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=group)
    setattr(app, "_star_selfie_handlers", True)
    return True


__all__ = ["register_handlers", "start", "menu_callback", "callback", "photo", "text_input", "cancel"]
