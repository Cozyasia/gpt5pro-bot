# -*- coding: utf-8 -*-
"""Reliable owner service menu for Celebrity Selfie.

The v201 menu checked only ``main.OWNER_ID`` and silently stopped when that
single value was empty or different.  This overlay accepts the project's normal
owner/unlimited settings, never fails silently, and owns the reference-upload
workflow at a higher PTB handler priority.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
from typing import Any

VERSION = "v202-selfie-admin-access-2026-07-25"
_BUILDER_HOOKED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        result: list[str] = []
        for item in value:
            result.extend(_tokens(item))
        return result
    return [part for part in re.split(r"[\s,;|]+", str(value).strip()) if part]


def _configured_ids(mod: Any) -> set[int]:
    values: list[Any] = [
        getattr(mod, "OWNER_ID", None),
        getattr(mod, "ADMIN_ID", None),
        getattr(mod, "ADMIN_IDS", None),
        getattr(mod, "UNLIM_USER_IDS", None),
        os.environ.get("OWNER_ID"),
        os.environ.get("SELFIE_ADMIN_IDS"),
        os.environ.get("ADMIN_IDS"),
        os.environ.get("UNLIM_USER_IDS"),
    ]
    result: set[int] = set()
    for value in values:
        for token in _tokens(value):
            with contextlib.suppress(Exception):
                parsed = int(token)
                if parsed > 0:
                    result.add(parsed)
    return result


def _configured_usernames(mod: Any) -> set[str]:
    values: list[Any] = [
        getattr(mod, "ADMIN_USERNAMES", None),
        getattr(mod, "UNLIM_USERNAMES", None),
        os.environ.get("SELFIE_ADMIN_USERNAMES"),
        os.environ.get("ADMIN_USERNAMES"),
        os.environ.get("UNLIM_USERNAMES"),
    ]
    result: set[str] = set()
    for value in values:
        for token in _tokens(value):
            normalized = token.strip().lstrip("@").lower()
            if normalized:
                result.add(normalized)
    return result


def is_admin(mod: Any, user: Any) -> bool:
    uid = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "").strip().lstrip("@").lower()
    if uid and uid in _configured_ids(mod):
        return True
    if username and username in _configured_usernames(mod):
        return True
    checker = getattr(mod, "is_unlimited", None)
    if callable(checker):
        with contextlib.suppress(Exception):
            if checker(uid, username):
                return True
    return False


def _admin_keyboard(mod: Any):
    return mod.InlineKeyboardMarkup([
        [mod.InlineKeyboardButton(
            "📤 Загрузить 3 JPEG Романа Абрамовича",
            callback_data="cs202:admin:upload:roman_abramovich",
        )],
        [mod.InlineKeyboardButton(
            "📊 Проверить статус референсов",
            callback_data="cs202:admin:status:roman_abramovich",
        )],
        [mod.InlineKeyboardButton(
            "🗑 Очистить референсы",
            callback_data="cs202:admin:clear:roman_abramovich",
        )],
        [mod.InlineKeyboardButton("⬅️ В AI-селфи", callback_data="cs201:open")],
    ])


def _denied_text(mod: Any, user: Any) -> str:
    uid = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "").strip().lstrip("@") or "—"
    owner_configured = "да" if _configured_ids(mod) or _configured_usernames(mod) else "нет"
    return (
        "⛔ Сервисное меню не открылось, потому что этот Telegram-аккаунт не найден в списке администраторов.\n\n"
        f"Ваш Telegram ID: {uid}\n"
        f"Username: @{username}\n"
        f"Администратор в Render настроен: {owner_configured}\n\n"
        "Добавьте ваш ID в Render → Environment в одну из переменных:\n"
        f"OWNER_ID={uid}\n"
        f"или SELFIE_ADMIN_IDS={uid}\n\n"
        "После сохранения дождитесь нового деплоя и снова отправьте /selfie_admin."
    )


async def command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    try:
        if mod is None or user is None or message is None:
            return
        if not is_admin(mod, user):
            await message.reply_text(_denied_text(mod, user))
            return
        from neyrobot_prod import celebrity_selfie as selfie
        # Keep the original module's callbacks and upload checks consistent with
        # this more complete access policy.
        selfie._is_owner = lambda runtime, candidate: is_admin(runtime, candidate)
        status = selfie._character_status(mod, "roman_abramovich")
        storage = selfie._storage_root(mod)
        await message.reply_text(
            f"🛠 Сервисное меню AI-селфи · {VERSION}\n\n"
            f"Роман Абрамович: {status}\n"
            f"Хранилище: {storage}\n\n"
            "Для активации героя нужны три отдельных JPEG-файла.",
            reply_markup=_admin_keyboard(mod),
        )
    finally:
        raise ApplicationHandlerStop


async def callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    query = getattr(update, "callback_query", None)
    try:
        if mod is None or query is None:
            return
        with contextlib.suppress(Exception):
            await query.answer()
        if not is_admin(mod, query.from_user):
            await query.message.reply_text(_denied_text(mod, query.from_user))
            return
        from neyrobot_prod import celebrity_selfie as selfie
        selfie._is_owner = lambda runtime, candidate: is_admin(runtime, candidate)
        parts = str(query.data or "").split(":")
        action = parts[2] if len(parts) > 2 else "status"
        slug = parts[3] if len(parts) > 3 else "roman_abramovich"
        if action == "upload":
            # Start from a clean three-image set so an old third photo cannot be
            # accidentally mixed with two newly uploaded references.
            for path in selfie._character_dir(mod, slug).glob("*.*"):
                with contextlib.suppress(Exception):
                    path.unlink()
            context.user_data["cs202_admin_upload"] = {"slug": slug, "received": 0}
            context.user_data.pop("cs201_admin_upload", None)
            await query.message.reply_text(
                "📤 Режим загрузки включён.\n"
                "Пришлите три отдельных JPEG-фото Романа Абрамовича по одному сообщению.\n"
                "После каждого файла бот подтвердит 1/3, 2/3 и 3/3."
            )
        elif action == "clear":
            for path in selfie._character_dir(mod, slug).glob("*.*"):
                with contextlib.suppress(Exception):
                    path.unlink()
            context.user_data.pop("cs202_admin_upload", None)
            await query.message.reply_text(
                f"🗑 Референсы очищены. Статус: {selfie._character_status(mod, slug)}",
                reply_markup=_admin_keyboard(mod),
            )
        else:
            await query.message.reply_text(
                f"📊 Роман Абрамович: {selfie._character_status(mod, slug)}\n"
                f"Готов к генерации: {'да' if selfie._character_ready(mod, slug) else 'нет'}",
                reply_markup=_admin_keyboard(mod),
            )
    finally:
        raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    state = context.user_data.get("cs202_admin_upload") or {}
    if not state:
        return
    mod = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "message", None)
    try:
        if mod is None or user is None or message is None:
            return
        if not is_admin(mod, user):
            context.user_data.pop("cs202_admin_upload", None)
            await message.reply_text(_denied_text(mod, user))
            return
        from neyrobot_prod import celebrity_selfie as selfie
        raw, _url = await selfie._download_photo_message(message)
        if not raw:
            await message.reply_text("⚠️ Нужен JPEG-файл или фотография, отправленная как фото.")
            return
        slug = str(state.get("slug") or "roman_abramovich")
        index, required = selfie._save_reference(mod, slug, raw)
        state["received"] = index
        context.user_data["cs202_admin_upload"] = state
        if index >= required:
            context.user_data.pop("cs202_admin_upload", None)
            await message.reply_text(
                f"✅ Все референсы загружены: {selfie._character_status(mod, slug)}.\n"
                "Герой активирован и доступен в режиме AI-селфи.",
                reply_markup=_admin_keyboard(mod),
            )
        else:
            await message.reply_text(f"✅ Референс {index}/{required} сохранён. Пришлите следующий JPEG.")
    finally:
        raise ApplicationHandlerStop


async def diag(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    user = update.effective_user
    lines = [
        "🛠 Selfie Admin diagnostic",
        f"version={VERSION}",
        f"user_id={getattr(user, 'id', 0)}",
        f"username=@{getattr(user, 'username', '') or '—'}",
        f"access={'on' if is_admin(mod, user) else 'off'}",
        f"configured_ids={len(_configured_ids(mod))}",
        f"configured_usernames={len(_configured_usernames(mod))}",
    ]
    with contextlib.suppress(Exception):
        from neyrobot_prod import celebrity_selfie as selfie
        lines.append(f"roman_abramovich={selfie._character_status(mod, 'roman_abramovich')}")
        lines.append(f"storage={selfie._storage_root(mod)}")
    await update.effective_message.reply_text("\n".join(lines))


def patch_runtime(mod: Any) -> bool:
    try:
        from neyrobot_prod import celebrity_selfie as selfie
        selfie._is_owner = lambda runtime, candidate: is_admin(runtime, candidate)
        mod.SELFIE_ADMIN_VERSION = VERSION
        return True
    except Exception:
        return False


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return False
    flag = "_selfie_admin_v202_builder"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, flag, False):
            app.add_handler(CommandHandler("selfie_admin", command), group=-45)
            app.add_handler(CommandHandler("diag_selfie_admin", diag), group=-45)
            app.add_handler(CallbackQueryHandler(callback, pattern=r"^cs202:admin:"), group=-45)
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media), group=-44)
            setattr(app, flag, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True
    return True


def install() -> None:
    install_builder_hook()
    mod = _runtime_module()
    if mod is not None:
        patch_runtime(mod)


__all__ = ["VERSION", "is_admin", "patch_runtime", "install_builder_hook", "install"]
