# -*- coding: utf-8 -*-
"""v124 final routing and Telegram-photo hardening for Celebrity Selfie.

This overlay owns the complete Celebrity Selfie conversation before every
legacy photo router.  It accepts both Telegram compressed photos and image
documents, starts a clean session without an error/fallback card and advances
straight to celebrity selection after the user selfie is received.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import celebrity_selfie_v122 as base
import celebrity_selfie_v123 as flow

VERSION = "v124-celebrity-selfie-telegram-photo-flow-2026-07-19"
_BUILDER_FLAG = "_celebrity_selfie_v124_builder"
_HANDLER_FLAG = "_celebrity_selfie_v124_handlers"
_ACTIVE_KEY = "_cs124_active"
_PATCH_LOCK: asyncio.Lock | None = None
log = logging.getLogger("gpt-bot.celebrity-selfie-v124")


ENTRY_CALLBACKS = {"act:fun:aiselfie", "pedit:aiselfie"}


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _user_data(context: Any) -> dict[str, Any]:
    data = getattr(context, "user_data", None)
    return data if isinstance(data, dict) else {}


def _is_active(context: Any) -> bool:
    data = _user_data(context)
    return bool(data.get(_ACTIVE_KEY)) and bool(base._session(context, create=False))


def _clear_feature_session(context: Any) -> None:
    data = _user_data(context)
    old = data.get(base._SESSION_KEY)
    with contextlib.suppress(Exception):
        base._clear_session(context)
    data.pop(base._SESSION_KEY, None)
    data.pop(_ACTIVE_KEY, None)
    if isinstance(old, dict):
        for key in ("work_dir", "session_dir", "temp_dir"):
            value = old.get(key)
            if value:
                with contextlib.suppress(Exception):
                    shutil.rmtree(str(value), ignore_errors=True)


def _cached_photo(update: Any) -> bytes | None:
    mod = base._runtime_module()
    getter = getattr(mod, "_get_cached_photo", None) if mod is not None else None
    if callable(getter):
        with contextlib.suppress(Exception):
            raw = getter(update.effective_user.id)
            if raw:
                return bytes(raw)
    return None


def _cache_photo(update: Any, raw: bytes) -> None:
    mod = base._runtime_module()
    setter = getattr(mod, "_cache_photo", None) if mod is not None else None
    if callable(setter):
        with contextlib.suppress(Exception):
            setter(update.effective_user.id, raw)


def _start_session(context: Any) -> dict[str, Any]:
    flow._clear_legacy_flows(context)
    _clear_feature_session(context)
    session = base._session(context)
    session.clear()
    session["state"] = "choose_user_photo"
    _user_data(context)[_ACTIVE_KEY] = True
    return session


async def _reply(update: Any, text: str, reply_markup: Any = None) -> None:
    await update.effective_message.reply_text(text, reply_markup=reply_markup)


async def _open_entry(update: Any, context: Any) -> None:
    """Open a clean first step; never display a recovery/error card."""
    session = _start_session(context)
    cached = _cached_photo(update)
    if cached:
        session["state"] = "choose_user_photo"
        await _reply(
            update,
            "📸 Точное AI-селфи со знаменитостью\n\n"
            "Выберите исходное фото. После выбора я сразу открою новое меню: "
            "российские знаменитости, американские знаменитости, поиск по имени "
            "или загрузка собственных референсов.",
            base._kb([
                [("✅ Использовать последнее фото", "celeb:use_cached")],
                [("📤 Загрузить новое селфи", "celeb:upload_user")],
                [("❌ Отмена", "celeb:cancel")],
            ]),
        )
        return
    session["state"] = "await_user_photo"
    await _reply(
        update,
        "📸 Точное AI-селфи со знаменитостью\n\n"
        "Пришлите своё чёткое фото обычной фотографией Telegram или файлом "
        "JPG/PNG/WEBP. После загрузки меню выбора знаменитости откроется автоматически.",
        base._kb([[("❌ Отмена", "celeb:cancel")]]),
    )


async def _download_telegram_image(update: Any, context: Any) -> bytes | None:
    """Accept Telegram PHOTO and image DOCUMENT without relying on a filename."""
    message = update.effective_message
    media = None
    photos = list(getattr(message, "photo", None) or [])
    if photos:
        media = photos[-1]
    else:
        document = getattr(message, "document", None)
        if document is not None:
            mime = str(getattr(document, "mime_type", "") or "").lower()
            name = str(getattr(document, "file_name", "") or "").lower()
            if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp")):
                media = document
    if media is None:
        return None

    tg_file = await context.bot.get_file(media.file_id)
    raw = b""
    try:
        buffer = BytesIO()
        await tg_file.download_to_memory(out=buffer)
        raw = buffer.getvalue()
    except Exception:
        with contextlib.suppress(Exception):
            raw = bytes(await tg_file.download_as_bytearray())
    return _normalize_image(raw)


def _normalize_image(raw: bytes) -> bytes | None:
    if not raw:
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")
            image.thumbnail((2048, 2048))
            out = BytesIO()
            image.save(out, format="JPEG", quality=93, optimize=True)
            data = out.getvalue()
            return data if len(data) >= 1024 else None
    except Exception as exc:
        log.warning("PIL normalization failed, checking image signature: %s", exc)
    if raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw
    return None


def _fallback_store(update: Any, filename: str, raw: bytes) -> str:
    root_value = os.environ.get("CELEBRITY_SESSION_ROOT", "/data/celebrity_sessions")
    root = Path(root_value)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path("/tmp/celebrity_sessions")
        root.mkdir(parents=True, exist_ok=True)
    user_dir = root / str(update.effective_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / f"{int(time.time())}_{uuid.uuid4().hex[:8]}_{filename}"
    path.write_bytes(raw)
    return str(path)


def _store_user_image(update: Any, session: dict[str, Any], raw: bytes) -> str:
    try:
        path = base._store_image(session, "user_selfie.jpg", raw)
        if path:
            return str(path)
    except Exception as exc:
        log.warning("base._store_image failed, using fallback: %s", exc)
    return _fallback_store(update, "user_selfie.jpg", raw)


async def _accept_user_photo(update: Any, context: Any, raw: bytes) -> None:
    session = base._session(context)
    session["user_photo_path"] = _store_user_image(update, session, raw)
    session["state"] = "choose_celebrity"
    _user_data(context)[_ACTIVE_KEY] = True
    _cache_photo(update, raw)
    await _reply(
        update,
        "✅ Селфи получено. Теперь выберите знаменитость.\n\n"
        "Для человека из каталога бот использует 3–4 референса. Если нужного человека "
        "нет в базе, можно загрузить 1–4 его фотографии.",
        base._main_menu_kb(),
    )


async def _delegate_custom_reference(update: Any, context: Any, raw: bytes) -> None:
    """Feed already-downloaded bytes to v122 without its legacy downloader."""
    global _PATCH_LOCK
    if _PATCH_LOCK is None:
        _PATCH_LOCK = asyncio.Lock()
    async with _PATCH_LOCK:
        original = getattr(base, "_download_image_from_update")

        async def supplied(_: Any) -> bytes:
            return raw

        base._download_image_from_update = supplied
        try:
            await base._on_image(update, context)
        finally:
            base._download_image_from_update = original


async def _callback(update: Any, context: Any) -> None:
    query = update.callback_query
    data = str(getattr(query, "data", "") or "")
    if data not in ENTRY_CALLBACKS and not data.startswith("celeb:"):
        return
    with contextlib.suppress(Exception):
        await query.answer()

    if data in ENTRY_CALLBACKS:
        try:
            await _open_entry(update, context)
        except Exception as exc:
            log.exception("Clean Celebrity Selfie entry failed: %s", exc)
            # One more clean attempt, without exposing an internal failure to the user.
            data_map = _user_data(context)
            data_map.pop(base._SESSION_KEY, None)
            session = base._session(context)
            session["state"] = "await_user_photo"
            data_map[_ACTIVE_KEY] = True
            await _reply(
                update,
                "📸 Точное AI-селфи со знаменитостью\n\nПришлите своё селфи обычной фотографией Telegram.",
                base._kb([[("❌ Отмена", "celeb:cancel")]]),
            )
        _stop()

    if data == "celeb:cancel":
        _clear_feature_session(context)
        flow._clear_legacy_flows(context)
        await _reply(update, "❌ Режим AI-селфи отменён. Можно выбрать другую функцию в разделе «Развлечения».")
        _stop()

    if not _is_active(context):
        await _reply(
            update,
            "Эта сессия уже завершена. Откройте режим AI-селфи заново.",
            base._kb([[('📸 Открыть AI-селфи', 'act:fun:aiselfie')]]),
        )
        _stop()

    flow._clear_legacy_flows(context)
    session = base._session(context)
    if data == "celeb:use_cached":
        raw = _cached_photo(update)
        if raw:
            await _accept_user_photo(update, context, raw)
        else:
            session["state"] = "await_user_photo"
            await _reply(
                update,
                "Последнее фото не найдено. Пришлите новое селфи обычной фотографией Telegram.",
                base._kb([[("❌ Отмена", "celeb:cancel")]]),
            )
        _stop()

    if data == "celeb:upload_user":
        session["state"] = "await_user_photo"
        await _reply(
            update,
            "📤 Пришлите новое селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP. "
            "После загрузки выбор знаменитости откроется автоматически.",
            base._kb([[("❌ Отмена", "celeb:cancel")]]),
        )
        _stop()

    try:
        await base._on_callback(update, context)
    except Exception as exc:
        log.exception("Celebrity Selfie submenu failed data=%s: %s", data, exc)
        await _reply(
            update,
            "Не удалось выполнить этот пункт. Выберите знаменитость другим способом.",
            base._main_menu_kb(),
        )
    _stop()


async def _image(update: Any, context: Any) -> None:
    if not _is_active(context):
        return
    flow._clear_legacy_flows(context)
    session = base._session(context)
    state = str(session.get("state") or "")
    try:
        raw = await _download_telegram_image(update, context)
        if not raw:
            await _reply(
                update,
                "Не удалось прочитать изображение. Отправьте его как обычное фото Telegram "
                "или как файл JPG/PNG/WEBP.",
                base._kb([[("❌ Отмена", "celeb:cancel")]]),
            )
            _stop()

        if state == "await_custom_refs":
            await _delegate_custom_reference(update, context, raw)
            _stop()
        if state == "generating":
            await _reply(update, "⏳ Генерация уже выполняется. Дождитесь результата.")
            _stop()
        if state in ("await_user_photo", "choose_user_photo", ""):
            await _accept_user_photo(update, context, raw)
            _stop()

        await _reply(
            update,
            "Селфи пользователя уже сохранено. Чтобы добавить фотографии знаменитости, "
            "нажмите «Загрузить фото знаменитости» в меню выбора.",
            base._main_menu_kb(),
        )
        _stop()
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Telegram image acceptance failed state=%s: %s", state, exc)
        session["state"] = "await_user_photo" if not session.get("user_photo_path") else "choose_celebrity"
        await _reply(
            update,
            "Фото не удалось обработать. Отправьте его ещё раз как обычное фото Telegram "
            "или как файл JPG/PNG/WEBP.",
            base._kb([[("❌ Отмена", "celeb:cancel")]]),
        )
        _stop()


async def _text(update: Any, context: Any) -> None:
    if not _is_active(context):
        return
    flow._clear_legacy_flows(context)
    session = base._session(context)
    state = str(session.get("state") or "")
    if state in ("await_user_photo", "choose_user_photo"):
        await _reply(
            update,
            "Сначала пришлите своё селфи или нажмите «Использовать последнее фото».",
            base._kb([
                [("✅ Использовать последнее фото", "celeb:use_cached")],
                [("📤 Загрузить новое селфи", "celeb:upload_user")],
                [("❌ Отмена", "celeb:cancel")],
            ]),
        )
        _stop()
    try:
        await flow._exclusive_text(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Exclusive Celebrity Selfie text failed: %s", exc)
        await _reply(update, "Продолжите текущий шаг кнопками меню.", base._main_menu_kb())
        _stop()
    _stop()


async def _diag(update: Any, context: Any) -> None:
    session = base._session(context, create=False)
    await _reply(
        update,
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if _is_active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        "callback_priority=-20000\n"
        "photo_priority=-20000\n"
        "telegram_photo=enabled\n"
        "image_document=enabled\n"
        "legacy_flow_blocked=yes",
    )


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(
                CallbackQueryHandler(_callback, pattern=r"^(?:act:fun:aiselfie|pedit:aiselfie|celeb:).*$"),
                group=-20000,
            )
            app.add_handler(
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, _image),
                group=-20000,
            )
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, _text),
                group=-20000,
            )
            app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=-20000)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = ["VERSION", "install_builder_hook"]
