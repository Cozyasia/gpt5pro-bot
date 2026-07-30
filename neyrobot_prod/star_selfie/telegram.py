from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from .catalog.store import CharacterCatalog
from .config import StarSelfieConfig
from .factory import build_pipeline
from .models import CaptureMode, GenerationRequest

_STATE_KEY = "star_selfie_flow"
_CALLBACK_PREFIX = "starselfie:"


def _catalog(config: StarSelfieConfig) -> CharacterCatalog:
    catalog_path = config.seed_catalog_path
    if not catalog_path.is_absolute():
        catalog_path = config.project_root / catalog_path
    return CharacterCatalog(catalog_path, config.persistent_root / "references")


def _state(context: Any) -> dict[str, Any]:
    return context.user_data.setdefault(_STATE_KEY, {})


def _clear(context: Any) -> None:
    context.user_data.pop(_STATE_KEY, None)


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

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📸 Фото со стороны", callback_data=f"{_CALLBACK_PREFIX}mode:{CaptureMode.THIRD_PERSON.value}")],
            [InlineKeyboardButton("🤳 Настоящее селфи", callback_data=f"{_CALLBACK_PREFIX}mode:{CaptureMode.TRUE_PHONE_SELFIE.value}")],
            [InlineKeyboardButton("✖️ Отмена", callback_data=f"{_CALLBACK_PREFIX}cancel")],
        ]
    )


async def start(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not config.enabled:
        await update.effective_message.reply_text("Функция «Селфи со звездой» пока отключена.")
        return

    characters = [
        item
        for item in _catalog(config).active()
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
        state.update({"step": "photo", "mode": mode.value})
        await query.edit_message_text(
            "Теперь отправьте одну чёткую фотографию лица анфас.\n"
            "Не используйте групповые фото, очки или сильные тени."
        )


async def photo(update: Any, context: Any, config: StarSelfieConfig) -> None:
    state = context.user_data.get(_STATE_KEY) or {}
    if state.get("step") != "photo" or not update.effective_message.photo:
        return

    character = _catalog(config).get(str(state.get("character") or ""))
    if character is None or not character.active:
        _clear(context)
        await update.effective_message.reply_text("Герой больше недоступен. Запустите /star_selfie заново.")
        return

    user_id = int(update.effective_user.id)
    incoming_dir = config.persistent_root / "incoming" / str(user_id)
    incoming_dir.mkdir(parents=True, exist_ok=True)
    source_path = incoming_dir / f"{update.effective_message.message_id}.jpg"
    telegram_file = await context.bot.get_file(update.effective_message.photo[-1].file_id)
    await telegram_file.download_to_drive(custom_path=source_path)

    state["step"] = "generating"
    progress = await update.effective_message.reply_text("⏳ Создаю сцену и переношу ваше лицо…")
    try:
        request = GenerationRequest(
            user_id=user_id,
            user_face_path=source_path,
            character=character,
            scene="A natural premium joint portrait with realistic lighting and coherent body geometry.",
            capture_mode=CaptureMode(str(state["mode"])),
        )
        result = await build_pipeline(config).run(request)
        with result.final_image_path.open("rb") as image:
            await update.effective_message.reply_photo(
                photo=image,
                caption=f"✅ Готово: {character.title}",
            )
        _clear(context)
    except Exception as exc:
        state["step"] = "photo"
        with contextlib.suppress(Exception):
            await progress.edit_text(
                "❌ Не удалось завершить генерацию. Отправьте фотографию ещё раз или отмените командой /cancel_star_selfie."
            )
        runtime = getattr(context.application, "bot_data", {}).get("star_selfie_runtime_logger")
        if runtime is not None:
            with contextlib.suppress(Exception):
                runtime.exception("Star Selfie generation failed", exc_info=exc)
    finally:
        with contextlib.suppress(OSError):
            await asyncio.to_thread(source_path.unlink)


async def cancel(update: Any, context: Any) -> None:
    existed = bool(context.user_data.get(_STATE_KEY))
    _clear(context)
    await update.effective_message.reply_text(
        "Создание селфи отменено." if existed else "Активной генерации селфи нет."
    )


def register_handlers(app: Any, config: StarSelfieConfig, *, group: int = -98) -> bool:
    """Register isolated PTB handlers. Safe to call repeatedly."""
    if not config.enabled or getattr(app, "_star_selfie_handlers", False):
        return False

    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    async def _start(update: Any, context: Any) -> None:
        await start(update, context, config)

    async def _callback(update: Any, context: Any) -> None:
        await callback(update, context, config)

    async def _photo(update: Any, context: Any) -> None:
        await photo(update, context, config)

    app.add_handler(CommandHandler("star_selfie", _start), group=group)
    app.add_handler(CommandHandler("cancel_star_selfie", cancel), group=group)
    app.add_handler(CallbackQueryHandler(_callback, pattern=r"^starselfie:"), group=group)
    app.add_handler(MessageHandler(filters.PHOTO, _photo), group=group)
    setattr(app, "_star_selfie_handlers", True)
    return True


__all__ = ["register_handlers", "start", "callback", "photo", "cancel"]
