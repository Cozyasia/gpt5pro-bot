# -*- coding: utf-8 -*-
"""Celebrity Selfie V205: persistent storage and multi-character administration.

This overlay makes /data/celebrity_selfie the only runtime reference root,
adds a second prepared character slot (Vlad A4 / Bumaga), and replaces the
single-character service menu with a generic owner/admin catalogue.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

VERSION = "v205-selfie-persistent-catalog-2026-07-25"
ROOT = Path("/data/celebrity_selfie")
_BUILDER_HOOKED = False
_WORKER_STARTED = False

CHARACTER_ADDITIONS: dict[str, dict[str, Any]] = {
    "vlad_a4_bumaga": {
        "name": "Влад А4 (Бумага)",
        "required_refs": 3,
        "aliases": ("влад а4", "а4 бумага", "влад бумага", "vlad a4", "a4 bumaga"),
    },
}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _ensure_root() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    probe = ROOT / ".persistent_write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return ROOT


def storage_root(mod: Any | None = None) -> Path:
    """Return only the persistent Render disk path; never source tree or /tmp."""
    return _ensure_root()


def _is_mount() -> bool:
    with contextlib.suppress(Exception):
        return os.path.ismount("/data")
    return False


def _csv_values(*names: str) -> set[str]:
    result: set[str] = set()
    for name in names:
        raw = str(os.environ.get(name, "") or "")
        for item in raw.replace(";", ",").split(","):
            value = item.strip().lstrip("@").lower()
            if value:
                result.add(value)
    return result


def _authorized(mod: Any, user: Any) -> bool:
    uid = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "").strip().lstrip("@").lower()
    if not uid:
        return False
    ids = _csv_values("SELFIE_ADMIN_IDS", "ADMIN_IDS", "UNLIM_USER_IDS")
    owner = int(getattr(mod, "OWNER_ID", 0) or 0)
    if uid == owner or str(uid) in ids:
        return True
    names = _csv_values("SELFIE_ADMIN_USERNAMES", "ADMIN_USERNAMES", "UNLIM_USERNAMES")
    if username and username in names:
        return True
    checker = getattr(mod, "is_unlimited", None)
    if callable(checker):
        with contextlib.suppress(Exception):
            if checker(uid):
                return True
    return False


def _base():
    from neyrobot_prod import celebrity_selfie as base
    return base


def _character_rows(mod: Any) -> list[list[Any]]:
    base = _base()
    rows: list[list[Any]] = []
    for slug, meta in base.CHARACTERS.items():
        status = base._character_status(mod, slug)
        ready = "✅" if base._character_ready(mod, slug) else "⬜"
        rows.append([
            mod.InlineKeyboardButton(
                f"{ready} {meta['name']} · {status}",
                callback_data=f"ss205:hero:{slug}",
            )
        ])
    rows.append([mod.InlineKeyboardButton("⬅️ В AI-селфи", callback_data="cs201:open")])
    return rows


def _catalog_kb(mod: Any):
    return mod.InlineKeyboardMarkup(_character_rows(mod))


def _hero_kb(mod: Any, slug: str):
    base = _base()
    meta = base.CHARACTERS.get(slug) or {"name": slug}
    return mod.InlineKeyboardMarkup([
        [mod.InlineKeyboardButton(f"📥 Загрузить 3 JPEG · {meta['name']}", callback_data=f"ss205:upload:{slug}")],
        [mod.InlineKeyboardButton("📊 Проверить статус", callback_data=f"ss205:status:{slug}")],
        [mod.InlineKeyboardButton("🗑 Очистить референсы", callback_data=f"ss205:clear:{slug}")],
        [mod.InlineKeyboardButton("⬅️ Ко всем героям", callback_data="ss205:catalog")],
    ])


def _status_text(mod: Any, slug: str) -> str:
    base = _base()
    meta = base.CHARACTERS.get(slug) or {"name": slug}
    ready = "да" if base._character_ready(mod, slug) else "нет"
    return (
        f"📊 {meta['name']}: {base._character_status(mod, slug)}\n"
        f"Готов к генерации: {ready}\n"
        f"Хранилище: {storage_root(mod) / 'characters' / slug}\n"
        f"Persistent disk /data: {'подключён' if _is_mount() else 'путь доступен, mount не подтверждён'}"
    )


async def admin_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    try:
        if mod is None:
            return
        if not _authorized(mod, update.effective_user):
            uid = int(getattr(update.effective_user, "id", 0) or 0)
            await update.effective_message.reply_text(
                f"⛔ Сервисное меню недоступно. Ваш Telegram ID: {uid}. "
                "Добавьте его в SELFIE_ADMIN_IDS или OWNER_ID."
            )
            return
        await update.effective_message.reply_text(
            f"🛠 Каталог AI-селфи · {VERSION}\n"
            f"Хранилище: {storage_root(mod)}\n"
            "Выберите героя:",
            reply_markup=_catalog_kb(mod),
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
        if not _authorized(mod, query.from_user):
            await query.message.reply_text("⛔ Нет доступа к сервисному каталогу.")
            return
        data = str(query.data or "")
        base = _base()
        if data == "ss205:catalog":
            await query.message.reply_text("🛠 Выберите героя:", reply_markup=_catalog_kb(mod))
            return
        parts = data.split(":", 2)
        if len(parts) != 3:
            return
        action, slug = parts[1], parts[2]
        meta = base.CHARACTERS.get(slug)
        if not meta:
            await query.message.reply_text("Неизвестный герой.", reply_markup=_catalog_kb(mod))
            return
        if action == "hero":
            await query.message.reply_text(_status_text(mod, slug), reply_markup=_hero_kb(mod, slug))
        elif action == "status":
            await query.message.reply_text(_status_text(mod, slug), reply_markup=_hero_kb(mod, slug))
        elif action == "upload":
            root = base._character_dir(mod, slug)
            for path in root.glob("*.*"):
                if path.suffix.lower() in {".jpg", ".jpeg"}:
                    with contextlib.suppress(Exception):
                        path.unlink()
            context.user_data["ss205_admin_upload"] = {"slug": slug, "count": 0}
            await query.message.reply_text(
                f"📥 Загрузка для «{meta['name']}» включена. Пришлите три JPEG по одному сообщению."
            )
        elif action == "clear":
            root = base._character_dir(mod, slug)
            for path in root.glob("*.*"):
                if path.suffix.lower() in {".jpg", ".jpeg"}:
                    with contextlib.suppress(Exception):
                        path.unlink()
            await query.message.reply_text(_status_text(mod, slug), reply_markup=_hero_kb(mod, slug))
    finally:
        raise ApplicationHandlerStop


async def _download_image(message: Any) -> bytes:
    if getattr(message, "photo", None):
        item = await message.photo[-1].get_file()
        return bytes(await item.download_as_bytearray())
    document = getattr(message, "document", None)
    if document:
        mime = str(getattr(document, "mime_type", "") or "").lower()
        name = str(getattr(document, "file_name", "") or "").lower()
        if mime in {"image/jpeg", "image/jpg"} or name.endswith((".jpg", ".jpeg")):
            item = await document.get_file()
            return bytes(await item.download_as_bytearray())
    return b""


async def media_entry(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    state = context.user_data.get("ss205_admin_upload") or {}
    if not state:
        return
    mod = _runtime_module()
    try:
        if mod is None or not _authorized(mod, update.effective_user):
            context.user_data.pop("ss205_admin_upload", None)
            return
        raw = await _download_image(update.effective_message)
        if not raw:
            await update.effective_message.reply_text("Нужен JPEG-файл или фотография в формате JPEG.")
            return
        slug = str(state.get("slug") or "")
        base = _base()
        meta = base.CHARACTERS.get(slug) or {"name": slug}
        index, required = base._save_reference(mod, slug, raw)
        state["count"] = index
        context.user_data["ss205_admin_upload"] = state
        if index >= required:
            context.user_data.pop("ss205_admin_upload", None)
            await update.effective_message.reply_text(
                f"✅ «{meta['name']}» активирован: {base._character_status(mod, slug)}.\n"
                f"Файлы сохранены в {base._character_dir(mod, slug)}",
                reply_markup=_hero_kb(mod, slug),
            )
        else:
            await update.effective_message.reply_text(f"✅ Референс {index}/{required} сохранён. Пришлите следующий JPEG.")
    finally:
        raise ApplicationHandlerStop


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    try:
        if mod is None:
            return
        base = _base()
        lines = [
            "💾 Selfie Storage diagnostic",
            f"version={VERSION}",
            f"storage={storage_root(mod)}",
            f"data_is_mount={'on' if _is_mount() else 'off'}",
            f"characters={len(base.CHARACTERS)}",
        ]
        for slug, meta in base.CHARACTERS.items():
            lines.append(
                f"{slug}={base._character_status(mod, slug)} ready={'on' if base._character_ready(mod, slug) else 'off'}"
            )
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


async def version_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    try:
        lines = [f"✅ Код запущен: {VERSION}"]
        if mod is not None:
            lines.extend([
                "Компоненты:",
                f"• медицина: {getattr(mod, 'MEDICAL_ENGINE_VERSION', '—')}",
                f"• медицинская карта: {getattr(mod, 'MEDICAL_CARD_VERSION', '—')}",
                f"• покупка кредитов: {getattr(mod, 'CREDIT_STORE_VERSION', '—')}",
                f"• AI-селфи: {getattr(mod, 'CELEBRITY_SELFIE_VERSION', '—')}",
                f"• хранилище героев: {VERSION}",
            ])
        lines.append("Render: main.py · Start Command: python -u main.py")
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def patch() -> bool:
    os.environ["CELEBRITY_SELFIE_DATA_DIR"] = str(ROOT)
    base = _base()
    base._storage_root = storage_root
    base.CHARACTERS.update(CHARACTER_ADDITIONS)
    for slug in base.CHARACTERS:
        (storage_root(None) / "characters" / slug).mkdir(parents=True, exist_ok=True)
    mod = _runtime_module()
    if mod is not None:
        mod.SELFIE_STORAGE_VERSION = VERSION
        mod.CELEBRITY_SELFIE_DATA_DIR = str(ROOT)
    return True


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return False
    flag = "_selfie_storage_v205_builder"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, flag, False):
            app.add_handler(CommandHandler("version", version_command), group=-1200)
            app.add_handler(CommandHandler("selfie_admin", admin_command), group=-100)
            app.add_handler(CommandHandler("diag_selfie_storage", diagnostic), group=-100)
            app.add_handler(CallbackQueryHandler(callback, pattern=r"^ss205:"), group=-100)
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media_entry), group=-99)
            setattr(app, flag, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True
    return True


def install_async() -> None:
    global _WORKER_STARTED
    install_builder_hook()
    patch()
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        # Hold the storage owner longer than all legacy selfie workers.
        stable = 0
        for _ in range(2400):
            try:
                patch()
                mod = _runtime_module()
                if mod is not None and callable(getattr(mod, "_try_pay_then_do", None)):
                    stable += 1
                    if stable >= 1200:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-storage-v205").start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION", "ROOT", "CHARACTER_ADDITIONS", "storage_root", "patch",
    "install_builder_hook", "install_async", "install",
]
