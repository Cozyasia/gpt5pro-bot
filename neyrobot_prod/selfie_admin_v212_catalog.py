# -*- coding: utf-8 -*-
"""V212 owner catalogue for uploading references for every selfie hero.

Keeps the public command ``/selfie_admin`` but replaces the old Roman-only
service menu with country and character selection. Each character owns an
independent set of three JPEG references on Render Persistent Disk.
"""
from __future__ import annotations

import contextlib
import sys
from typing import Any

VERSION = "v212-selfie-admin-full-catalog-2026-07-26"
_BUILDER_HOOKED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _modules() -> tuple[Any, Any, Any]:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_admin_v202 as legacy_admin
    from neyrobot_prod import selfie_v208_overlay as catalog

    # Keep the canonical catalogue visible to storage/status helpers.
    base.CHARACTERS.update(catalog.CHARACTERS)
    return base, legacy_admin, catalog


def _is_admin(mod: Any, user: Any) -> bool:
    _base, legacy_admin, _catalog = _modules()
    return bool(legacy_admin.is_admin(mod, user))


def _denied(mod: Any, user: Any) -> str:
    _base, legacy_admin, _catalog = _modules()
    return legacy_admin._denied_text(mod, user)


def _country_keyboard(mod: Any):
    base, _legacy_admin, catalog = _modules()
    rows = []
    for code, (label, _title) in catalog.COUNTRIES.items():
        total = sum(1 for meta in base.CHARACTERS.values() if meta.get("country") == code)
        ready = sum(
            1 for slug, meta in base.CHARACTERS.items()
            if meta.get("country") == code and base._character_ready(mod, slug)
        )
        rows.append([mod.InlineKeyboardButton(
            f"{label} · {ready}/{total}",
            callback_data=f"cs212:admin:country:{code}",
        )])
    rows.append([mod.InlineKeyboardButton("📊 Статус всех героев", callback_data="cs212:admin:all")])
    rows.append([mod.InlineKeyboardButton("⬅️ В AI-селфи", callback_data="cs201:open")])
    return mod.InlineKeyboardMarkup(rows)


def _character_keyboard(mod: Any, country: str):
    base, _legacy_admin, catalog = _modules()
    rows = []
    for slug, meta in base.CHARACTERS.items():
        if meta.get("country") != country:
            continue
        status = base._character_status(mod, slug)
        mark = "✅" if base._character_ready(mod, slug) else "⚠️"
        rows.append([mod.InlineKeyboardButton(
            f"{mark} {meta['name']} · {status}",
            callback_data=f"cs212:admin:hero:{slug}",
        )])
    title = catalog.COUNTRIES.get(country, ("Герои", "Герои"))[1]
    rows.append([mod.InlineKeyboardButton("⬅️ К странам", callback_data="cs212:admin:root")])
    return title, mod.InlineKeyboardMarkup(rows)


def _hero_keyboard(mod: Any, slug: str):
    base, _legacy_admin, _catalog = _modules()
    meta = base.CHARACTERS.get(slug) or {}
    country = str(meta.get("country") or "ru")
    return mod.InlineKeyboardMarkup([
        [mod.InlineKeyboardButton("📤 Загрузить 3 JPEG", callback_data=f"cs212:admin:upload:{slug}")],
        [mod.InlineKeyboardButton("📊 Проверить статус", callback_data=f"cs212:admin:status:{slug}")],
        [mod.InlineKeyboardButton("🗑 Очистить референсы", callback_data=f"cs212:admin:clear:{slug}")],
        [mod.InlineKeyboardButton("⬅️ К списку героев", callback_data=f"cs212:admin:country:{country}")],
    ])


def _summary(mod: Any) -> str:
    base, _legacy_admin, _catalog = _modules()
    total = len(base.CHARACTERS)
    ready = sum(1 for slug in base.CHARACTERS if base._character_ready(mod, slug))
    return (
        f"🛠 Сервисное меню AI-селфи · {VERSION}\n\n"
        f"Активировано героев: {ready}/{total}\n"
        f"Хранилище: {base._storage_root(mod)}\n\n"
        "Выберите страну, затем героя. Для каждого героя загрузите три отдельных JPEG-фото по одному сообщению."
    )


async def command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    mod = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    try:
        if mod is None or user is None or message is None:
            return
        if not _is_admin(mod, user):
            await message.reply_text(_denied(mod, user))
            return
        await message.reply_text(_summary(mod), reply_markup=_country_keyboard(mod))
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
        if not _is_admin(mod, query.from_user):
            await query.message.reply_text(_denied(mod, query.from_user))
            return

        base, _legacy_admin, catalog = _modules()
        parts = str(query.data or "").split(":")
        action = parts[2] if len(parts) > 2 else "root"
        value = parts[3] if len(parts) > 3 else ""

        if action == "root":
            await query.message.reply_text(_summary(mod), reply_markup=_country_keyboard(mod))
            return

        if action == "country":
            country = value if value in catalog.COUNTRIES else "ru"
            title, keyboard = _character_keyboard(mod, country)
            await query.message.reply_text(f"⭐ {title}: выберите героя для загрузки референсов.", reply_markup=keyboard)
            return

        if action == "all":
            lines = ["📊 Статус референсов всех героев:"]
            for code, (_label, title) in catalog.COUNTRIES.items():
                lines.append(f"\n{title}:")
                for slug, meta in base.CHARACTERS.items():
                    if meta.get("country") == code:
                        mark = "✅" if base._character_ready(mod, slug) else "⚠️"
                        lines.append(f"{mark} {meta['name']}: {base._character_status(mod, slug)}")
            await query.message.reply_text("\n".join(lines), reply_markup=_country_keyboard(mod))
            return

        slug = value
        meta = base.CHARACTERS.get(slug)
        if not meta:
            await query.message.reply_text("Герой не найден. Откройте /selfie_admin заново.")
            return

        if action == "hero" or action == "status":
            await query.message.reply_text(
                f"⭐ {meta['name']}\n"
                f"Референсы: {base._character_status(mod, slug)}\n"
                f"Готов к генерации: {'да' if base._character_ready(mod, slug) else 'нет'}",
                reply_markup=_hero_keyboard(mod, slug),
            )
            return

        if action == "upload":
            # Replace the complete set atomically from the owner's perspective:
            # an old third reference must never be mixed with two new files.
            for path in base._character_dir(mod, slug).glob("*.*"):
                with contextlib.suppress(Exception):
                    path.unlink()
            context.user_data["cs212_admin_upload"] = {"slug": slug, "received": 0}
            context.user_data.pop("cs202_admin_upload", None)
            context.user_data.pop("cs201_admin_upload", None)
            await query.message.reply_text(
                f"📤 Загрузка референсов: {meta['name']}.\n\n"
                "Пришлите три отдельных JPEG-фото по одному сообщению. "
                "Бот подтвердит 1/3, 2/3 и 3/3."
            )
            return

        if action == "clear":
            for path in base._character_dir(mod, slug).glob("*.*"):
                with contextlib.suppress(Exception):
                    path.unlink()
            context.user_data.pop("cs212_admin_upload", None)
            await query.message.reply_text(
                f"🗑 Референсы «{meta['name']}» очищены. Статус: {base._character_status(mod, slug)}",
                reply_markup=_hero_keyboard(mod, slug),
            )
            return
    finally:
        raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    state = context.user_data.get("cs212_admin_upload") or {}
    if not state:
        return
    mod = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "message", None)
    try:
        if mod is None or user is None or message is None:
            return
        if not _is_admin(mod, user):
            context.user_data.pop("cs212_admin_upload", None)
            await message.reply_text(_denied(mod, user))
            return

        base, _legacy_admin, _catalog = _modules()
        slug = str(state.get("slug") or "")
        meta = base.CHARACTERS.get(slug)
        if not meta:
            context.user_data.pop("cs212_admin_upload", None)
            await message.reply_text("Герой не найден. Начните заново: /selfie_admin")
            return

        raw, _url = await base._download_photo_message(message)
        if not raw:
            await message.reply_text("⚠️ Нужен JPEG-файл или фотография, отправленная как фото.")
            return

        index, required = base._save_reference(mod, slug, raw)
        state["received"] = index
        context.user_data["cs212_admin_upload"] = state
        if index >= required:
            context.user_data.pop("cs212_admin_upload", None)
            await message.reply_text(
                f"✅ {meta['name']}: все референсы загружены — {base._character_status(mod, slug)}.\n"
                "Герой активирован и доступен в AI-селфи.",
                reply_markup=_hero_keyboard(mod, slug),
            )
        else:
            await message.reply_text(
                f"✅ {meta['name']}: референс {index}/{required} сохранён. Пришлите следующий JPEG."
            )
    finally:
        raise ApplicationHandlerStop


async def diag(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    base, _legacy_admin, _catalog = _modules()
    ready = sum(1 for slug in base.CHARACTERS if base._character_ready(mod, slug))
    await update.effective_message.reply_text(
        "🛠 Selfie Admin catalogue diagnostic\n"
        f"version={VERSION}\n"
        f"access={'on' if _is_admin(mod, update.effective_user) else 'off'}\n"
        f"characters={len(base.CHARACTERS)}\n"
        f"ready={ready}\n"
        f"storage={base._storage_root(mod)}"
    )


def patch_runtime() -> bool:
    mod = _runtime_module()
    if mod is None:
        return False
    base, legacy_admin, _catalog = _modules()
    base._is_owner = lambda runtime, candidate: legacy_admin.is_admin(runtime, candidate)
    mod.SELFIE_ADMIN_VERSION = VERSION
    return True


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return False

    flag = "_selfie_admin_v212_catalog_builder"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, flag, False):
            # Earlier groups own /selfie_admin before the Roman-only V202 handlers.
            app.add_handler(CommandHandler("selfie_admin", command), group=-212)
            app.add_handler(CommandHandler("diag_selfie_admin_catalog", diag), group=-212)
            app.add_handler(CallbackQueryHandler(callback, pattern=r"^cs212:admin:"), group=-212)
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media), group=-211)
            setattr(app, flag, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True
    return True


def install() -> None:
    install_builder_hook()
    with contextlib.suppress(Exception):
        patch_runtime()


__all__ = ["VERSION", "command", "callback", "media", "diag", "patch_runtime", "install_builder_hook", "install"]
