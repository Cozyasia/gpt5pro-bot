from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .catalog.store import CharacterCatalog
from .config import StarSelfieConfig
from .models import Character

_ADMIN_STATE_KEY = "star_selfie_admin"
_ADMIN_CALLBACK_PREFIX = "staradmin:"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")


def _catalog(config: StarSelfieConfig) -> CharacterCatalog:
    catalog_path = config.seed_catalog_path
    if not catalog_path.is_absolute():
        catalog_path = config.project_root / catalog_path
    return CharacterCatalog(catalog_path, config.persistent_root / "references")


def _runtime_owner_id() -> int:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None:
            with contextlib.suppress(TypeError, ValueError):
                return int(getattr(module, "OWNER_ID", 0) or 0)
    return 0


def _configured_admin_ids() -> set[int]:
    result: set[int] = set()
    for raw in (os.getenv("STAR_SELFIE_ADMIN_IDS", ""), os.getenv("OWNER_ID", "")):
        for item in raw.replace(";", ",").split(","):
            with contextlib.suppress(TypeError, ValueError):
                value = int(item.strip())
                if value > 0:
                    result.add(value)
    runtime_owner = _runtime_owner_id()
    if runtime_owner > 0:
        result.add(runtime_owner)
    return result


def is_admin(user: Any) -> bool:
    user_id = int(getattr(user, "id", 0) or 0)
    return user_id > 0 and user_id in _configured_admin_ids()


def _state(context: Any) -> dict[str, Any]:
    return context.user_data.setdefault(_ADMIN_STATE_KEY, {})


def _clear(context: Any) -> None:
    context.user_data.pop(_ADMIN_STATE_KEY, None)


def _menu_keyboard(characters: list[Character]):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton("➕ Добавить героя", callback_data=f"{_ADMIN_CALLBACK_PREFIX}create")]]
    for character in characters:
        icon = "🟢" if character.active else "⚪️"
        rows.append([
            InlineKeyboardButton(
                f"{icon} {character.title} ({len(character.reference_paths)})",
                callback_data=f"{_ADMIN_CALLBACK_PREFIX}open:{character.slug}",
            )
        ])
    rows.append([InlineKeyboardButton("✖️ Закрыть", callback_data=f"{_ADMIN_CALLBACK_PREFIX}close")])
    return InlineKeyboardMarkup(rows)


def _character_keyboard(character: Character):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    toggle = "⏸ Отключить" if character.active else "▶️ Активировать"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Загрузить референсы", callback_data=f"{_ADMIN_CALLBACK_PREFIX}upload:{character.slug}")],
        [InlineKeyboardButton(toggle, callback_data=f"{_ADMIN_CALLBACK_PREFIX}toggle:{character.slug}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"{_ADMIN_CALLBACK_PREFIX}delete_confirm:{character.slug}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{_ADMIN_CALLBACK_PREFIX}menu")],
    ])


def _character_text(character: Character) -> str:
    ready = 3 <= len(character.reference_paths) <= 6 and all(path.is_file() for path in character.reference_paths)
    return (
        f"⭐ {character.title}\n"
        f"slug: {character.slug}\n"
        f"Статус: {'активен' if character.active else 'отключён'}\n"
        f"Референсы: {len(character.reference_paths)}/3–6\n"
        f"Готовность: {'✅' if ready else '❌'}"
    )


async def start(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text("Команда доступна владельцу бота.")
        return
    _clear(context)
    characters = _catalog(config).load()
    await update.effective_message.reply_text(
        "🛠 Управление каталогом Star Selfie",
        reply_markup=_menu_keyboard(characters),
    )


async def callback(update: Any, context: Any, config: StarSelfieConfig) -> None:
    query = update.callback_query
    if query is None or not (query.data or "").startswith(_ADMIN_CALLBACK_PREFIX):
        return
    if not is_admin(update.effective_user):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    await query.answer()
    action = query.data[len(_ADMIN_CALLBACK_PREFIX):]
    catalog = _catalog(config)

    if action == "close":
        _clear(context)
        await query.edit_message_text("Админ-панель закрыта.")
        return
    if action == "menu":
        _clear(context)
        await query.edit_message_text("🛠 Управление каталогом Star Selfie", reply_markup=_menu_keyboard(catalog.load()))
        return
    if action == "create":
        _state(context).update({"step": "create_title"})
        await query.edit_message_text("Введите отображаемое имя героя, например: Роман Абрамович")
        return
    if action.startswith("open:"):
        character = catalog.get(action.split(":", 1)[1])
        if character is None:
            await query.edit_message_text("Герой не найден.")
            return
        await query.edit_message_text(_character_text(character), reply_markup=_character_keyboard(character))
        return
    if action.startswith("upload:"):
        slug = action.split(":", 1)[1]
        character = catalog.get(slug)
        if character is None:
            await query.edit_message_text("Герой не найден.")
            return
        _state(context).update({"step": "upload", "slug": slug})
        await query.edit_message_text(
            "Отправьте 3–6 фотографий героя по одной. Когда закончите, используйте /star_admin_done.\n"
            "Новая загрузка заменит старый набор после успешного завершения."
        )
        return
    if action.startswith("toggle:"):
        slug = action.split(":", 1)[1]
        characters = catalog.load()
        character = next((item for item in characters if item.slug == slug), None)
        if character is None:
            await query.edit_message_text("Герой не найден.")
            return
        ready = 3 <= len(character.reference_paths) <= 6 and all(path.is_file() for path in character.reference_paths)
        if not character.active and not ready:
            await query.edit_message_text("Нельзя активировать героя: сначала загрузите 3–6 референсов.", reply_markup=_character_keyboard(character))
            return
        character.active = not character.active
        catalog.save(characters)
        await query.edit_message_text(_character_text(character), reply_markup=_character_keyboard(character))
        return
    if action.startswith("delete_confirm:"):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        slug = action.split(":", 1)[1]
        await query.edit_message_text(
            f"Удалить героя {slug} и все его референсы?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Да, удалить", callback_data=f"{_ADMIN_CALLBACK_PREFIX}delete:{slug}")],
                [InlineKeyboardButton("Отмена", callback_data=f"{_ADMIN_CALLBACK_PREFIX}open:{slug}")],
            ]),
        )
        return
    if action.startswith("delete:"):
        slug = action.split(":", 1)[1]
        characters = [item for item in catalog.load() if item.slug != slug]
        catalog.save(characters)
        shutil.rmtree(config.persistent_root / "references" / slug, ignore_errors=True)
        _clear(context)
        await query.edit_message_text("Герой удалён.", reply_markup=_menu_keyboard(characters))


async def text(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not is_admin(update.effective_user):
        return
    state = context.user_data.get(_ADMIN_STATE_KEY) or {}
    message_text = (update.effective_message.text or "").strip()
    catalog = _catalog(config)
    if state.get("step") == "create_title":
        if len(message_text) < 2 or len(message_text) > 80:
            await update.effective_message.reply_text("Имя должно содержать от 2 до 80 символов.")
            return
        state.update({"step": "create_slug", "title": message_text})
        await update.effective_message.reply_text("Введите slug латиницей: например roman_abramovich")
        return
    if state.get("step") == "create_slug":
        slug = message_text.lower()
        if not _SLUG_RE.fullmatch(slug):
            await update.effective_message.reply_text("Slug: 2–64 символа, только a-z, цифры и _. Начните с буквы или цифры.")
            return
        if catalog.get(slug) is not None:
            await update.effective_message.reply_text("Такой slug или алиас уже существует.")
            return
        characters = catalog.load()
        character = Character(slug=slug, title=str(state["title"]), aliases=[], active=False, reference_paths=[], source="admin")
        characters.append(character)
        catalog.save(characters)
        _clear(context)
        await update.effective_message.reply_text(
            "✅ Герой создан. Теперь загрузите 3–6 референсов через /star_admin.",
            reply_markup=_character_keyboard(character),
        )


async def photo(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not is_admin(update.effective_user):
        return
    state = context.user_data.get(_ADMIN_STATE_KEY) or {}
    if state.get("step") != "upload" or not update.effective_message.photo:
        return
    slug = str(state.get("slug") or "")
    character = _catalog(config).get(slug)
    if character is None:
        _clear(context)
        await update.effective_message.reply_text("Герой не найден.")
        return
    staging = config.persistent_root / "admin_uploads" / str(update.effective_user.id) / slug
    staging.mkdir(parents=True, exist_ok=True)
    current = sorted(staging.glob("ref_*.jpg"))
    if len(current) >= config.max_character_refs:
        await update.effective_message.reply_text("Уже загружено 6 фотографий. Завершите командой /star_admin_done.")
        return
    path = staging / f"ref_{len(current) + 1:02d}.jpg"
    telegram_file = await context.bot.get_file(update.effective_message.photo[-1].file_id)
    await telegram_file.download_to_drive(custom_path=path)
    await update.effective_message.reply_text(f"✅ Загружено {len(current) + 1}/3–6")


async def done(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text("Команда доступна владельцу бота.")
        return
    state = context.user_data.get(_ADMIN_STATE_KEY) or {}
    if state.get("step") != "upload":
        await update.effective_message.reply_text("Нет активной загрузки референсов.")
        return
    slug = str(state.get("slug") or "")
    staging = config.persistent_root / "admin_uploads" / str(update.effective_user.id) / slug
    files = sorted(staging.glob("ref_*.jpg"))
    if not config.required_character_refs <= len(files) <= config.max_character_refs:
        await update.effective_message.reply_text("Нужно загрузить от 3 до 6 фотографий.")
        return
    target = config.persistent_root / "references" / slug
    temp_target = target.with_name(target.name + ".new")
    shutil.rmtree(temp_target, ignore_errors=True)
    temp_target.mkdir(parents=True, exist_ok=True)
    for source in files:
        shutil.copy2(source, temp_target / source.name)
    old_target = target.with_name(target.name + ".old")
    shutil.rmtree(old_target, ignore_errors=True)
    if target.exists():
        target.replace(old_target)
    temp_target.replace(target)
    shutil.rmtree(old_target, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)

    catalog = _catalog(config)
    characters = catalog.load()
    character = next((item for item in characters if item.slug == slug), None)
    if character is None:
        await update.effective_message.reply_text("Герой не найден в каталоге.")
        _clear(context)
        return
    character.reference_paths = sorted(target.glob("ref_*.jpg"))
    catalog.save(characters)
    _clear(context)
    await update.effective_message.reply_text(
        f"✅ Сохранено {len(character.reference_paths)} референсов. Герой пока {'активен' if character.active else 'отключён'}.",
        reply_markup=_character_keyboard(character),
    )


def register_handlers(app: Any, config: StarSelfieConfig, *, group: int = -97) -> bool:
    if not config.enabled or getattr(app, "_star_selfie_admin_handlers", False):
        return False
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    async def _start(update: Any, context: Any) -> None:
        await start(update, context, config)

    async def _callback(update: Any, context: Any) -> None:
        await callback(update, context, config)

    async def _text(update: Any, context: Any) -> None:
        await text(update, context, config)

    async def _photo(update: Any, context: Any) -> None:
        await photo(update, context, config)

    async def _done(update: Any, context: Any) -> None:
        await done(update, context, config)

    app.add_handler(CommandHandler("star_admin", _start), group=group)
    app.add_handler(CommandHandler("star_admin_done", _done), group=group)
    app.add_handler(CallbackQueryHandler(_callback, pattern=r"^staradmin:"), group=group)
    app.add_handler(MessageHandler(filters.PHOTO, _photo), group=group)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=group)
    setattr(app, "_star_selfie_admin_handlers", True)
    return True


__all__ = ["register_handlers", "start", "callback", "text", "photo", "done", "is_admin"]
