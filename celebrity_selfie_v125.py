# -*- coding: utf-8 -*-
"""Single-owner routing for the exact Celebrity Selfie wizard.

v124 proved that Telegram-photo support is present, but v123/v124 handlers were
both installed at runtime.  That allowed one update to fall through to an older
handler and produced duplicate diagnostics, recovery cards and the legacy
"photo could not be accepted" response.  v125 is the only high-priority owner
of the conversation.  Older modules are imported only as implementation
libraries; their builder hooks are no longer installed.
"""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from io import BytesIO
from typing import Any

import celebrity_selfie_v122 as base
import celebrity_selfie_v123 as legacy_flow
import celebrity_selfie_v124 as core

VERSION = "v125-celebrity-selfie-single-owner-2026-07-19"
_BUILDER_FLAG = "_celebrity_selfie_v125_builder"
_HANDLER_FLAG = "_celebrity_selfie_v125_handlers"
_GROUP = -30000
log = logging.getLogger("gpt-bot.celebrity-selfie-v125")

_ENTRY_MARKERS = (
    "aiselfie",
    "ai-selfie",
    "ai_selfie",
    "celebrity_selfie",
    "celebrity-selfie",
    "selfie_star",
)
_NAVIGATION_TEXTS = {
    "развлечения",
    "🔥 развлечения",
    "назад",
    "⬅️ назад",
    "меню ботов",
    "главное меню",
    "учёба",
    "работа бизнес",
    "работа/бизнес",
    "медицина",
    "движки",
    "о боте",
}


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _text_key(value: str) -> str:
    return " ".join((value or "").casefold().replace("—", " ").replace("-", " ").split())


def _is_entry_callback(data: str) -> bool:
    value = (data or "").casefold()
    return any(marker in value for marker in _ENTRY_MARKERS)


def _is_celebrity_callback(data: str) -> bool:
    return (data or "").startswith("celeb:")


def _active(context: Any) -> bool:
    return bool(core._is_active(context))


def _clear_all(context: Any) -> None:
    with contextlib.suppress(Exception):
        core._clear_feature_session(context)
    with contextlib.suppress(Exception):
        legacy_flow._clear_legacy_flows(context)


async def _send_clean_upload_step(update: Any, context: Any) -> None:
    """Emergency clean entry that never exposes an internal recovery message."""
    _clear_all(context)
    session = base._session(context)
    session.clear()
    session["state"] = "await_user_photo"
    session["flow_owner"] = VERSION
    context.user_data[core._ACTIVE_KEY] = True
    await update.effective_message.reply_text(
        "📸 Точное AI-селфи со знаменитостью\n\n"
        "Пришлите своё чёткое селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP. "
        "После загрузки меню выбора знаменитости откроется автоматически.",
        reply_markup=base._kb([[("❌ Отмена", "celeb:cancel")]]),
    )


async def _open_entry(update: Any, context: Any) -> None:
    try:
        await core._open_entry(update, context)
        session = base._session(context)
        session["flow_owner"] = VERSION
    except Exception as exc:
        log.exception("v125 clean entry fallback: %s", exc)
        await _send_clean_upload_step(update, context)


async def _callback(update: Any, context: Any) -> None:
    query = update.callback_query
    data = str(getattr(query, "data", "") or "")
    ours = _is_entry_callback(data) or _is_celebrity_callback(data)

    # Any unrelated inline-button click means the user left this wizard.  Clear
    # stale state and let the target feature's own handler process the update.
    if not ours:
        if _active(context):
            _clear_all(context)
        return

    with contextlib.suppress(Exception):
        await query.answer()

    if _is_entry_callback(data) and not _is_celebrity_callback(data):
        await _open_entry(update, context)
        _stop()

    if not _active(context):
        await _send_clean_upload_step(update, context)
        _stop()

    try:
        await core._callback(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("v125 callback failed data=%s: %s", data, exc)
        session = base._session(context)
        if session.get("user_photo_path"):
            session["state"] = "choose_celebrity"
            await update.effective_message.reply_text(
                "Продолжите выбор знаменитости:",
                reply_markup=base._main_menu_kb(),
            )
        else:
            await _send_clean_upload_step(update, context)
        _stop()
    _stop()


async def _download_file_bytes(media: Any, context: Any) -> bytes:
    tg_file = None
    get_file = getattr(media, "get_file", None)
    if callable(get_file):
        with contextlib.suppress(Exception):
            tg_file = await get_file()
    if tg_file is None:
        tg_file = await context.bot.get_file(media.file_id)

    # PTB versions differ in which output object download_to_memory accepts.
    # Try bytearray first, then BytesIO, then the direct and drive fallbacks.
    out = bytearray()
    try:
        result = await tg_file.download_to_memory(out=out)
        raw = bytes(out)
        if not raw and result is not None:
            raw = bytes(result)
        if raw:
            return raw
    except Exception as exc:
        log.info("download_to_memory(bytearray) failed: %s", exc)

    try:
        buffer = BytesIO()
        result = await tg_file.download_to_memory(out=buffer)
        raw = buffer.getvalue()
        if not raw and result is not None and not isinstance(result, str):
            raw = bytes(result)
        if raw:
            return raw
    except Exception as exc:
        log.info("download_to_memory(BytesIO) failed: %s", exc)

    download_as_bytearray = getattr(tg_file, "download_as_bytearray", None)
    if callable(download_as_bytearray):
        try:
            raw = bytes(await download_as_bytearray())
            if raw:
                return raw
        except Exception as exc:
            log.info("download_as_bytearray failed: %s", exc)

    download_to_drive = getattr(tg_file, "download_to_drive", None)
    if callable(download_to_drive):
        fd, path = tempfile.mkstemp(prefix="celeb-selfie-", suffix=".img")
        os.close(fd)
        try:
            await download_to_drive(custom_path=path)
            with open(path, "rb") as source:
                raw = source.read()
            if raw:
                return raw
        finally:
            with contextlib.suppress(Exception):
                os.remove(path)
    return b""


async def _download_image(update: Any, context: Any) -> bytes | None:
    message = update.effective_message
    photos = list(getattr(message, "photo", None) or [])
    media = photos[-1] if photos else None

    if media is None:
        document = getattr(message, "document", None)
        if document is not None:
            mime = str(getattr(document, "mime_type", "") or "").casefold()
            filename = str(getattr(document, "file_name", "") or "").casefold()
            if mime.startswith("image/") or filename.endswith((".jpg", ".jpeg", ".png", ".webp")):
                media = document
    if media is None:
        return None

    raw = await _download_file_bytes(media, context)
    return core._normalize_image(raw)


async def _image(update: Any, context: Any) -> None:
    if not _active(context):
        return
    legacy_flow._clear_legacy_flows(context)
    session = base._session(context)
    state = str(session.get("state") or "")
    try:
        raw = await _download_image(update, context)
        if not raw:
            await update.effective_message.reply_text(
                "Не удалось скачать изображение из Telegram. Отправьте его ещё раз обычной фотографией "
                "или файлом JPG/PNG/WEBP.",
                reply_markup=base._kb([[("❌ Отмена", "celeb:cancel")]]),
            )
            _stop()

        if state == "await_custom_refs":
            await core._delegate_custom_reference(update, context, raw)
            _stop()
        if state == "generating":
            await update.effective_message.reply_text("⏳ Генерация уже выполняется. Дождитесь результата.")
            _stop()
        if state in ("await_user_photo", "choose_user_photo", ""):
            await core._accept_user_photo(update, context, raw)
            base._session(context)["flow_owner"] = VERSION
            _stop()

        await update.effective_message.reply_text(
            "Селфи уже сохранено. Для загрузки фотографий знаменитости нажмите соответствующую кнопку в меню.",
            reply_markup=base._main_menu_kb(),
        )
        _stop()
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("v125 photo handler failed state=%s: %s", state, exc)
        session["state"] = "await_user_photo" if not session.get("user_photo_path") else "choose_celebrity"
        await update.effective_message.reply_text(
            "Фото не удалось обработать. Отправьте его ещё раз обычной фотографией Telegram "
            "или файлом JPG/PNG/WEBP.",
            reply_markup=(base._main_menu_kb() if session.get("user_photo_path") else base._kb([[("❌ Отмена", "celeb:cancel")]])),
        )
        _stop()


async def _text(update: Any, context: Any) -> None:
    if not _active(context):
        return
    text = str(getattr(update.effective_message, "text", "") or "")
    if _text_key(text) in _NAVIGATION_TEXTS:
        _clear_all(context)
        return
    try:
        await core._text(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("v125 text handler failed: %s", exc)
        await update.effective_message.reply_text(
            "Продолжите текущий шаг кнопками меню.",
            reply_markup=base._main_menu_kb(),
        )
        _stop()
    _stop()


async def _diag(update: Any, context: Any) -> None:
    session = base._session(context, create=False)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if _active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('flow_owner', '-') if session else '-'}\n"
        f"callback_priority={_GROUP}\n"
        f"photo_priority={_GROUP}\n"
        "telegram_photo=enabled\n"
        "image_document=enabled\n"
        "single_owner=yes\n"
        "legacy_v123_handlers=disabled",
    )
    _stop()


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
            # Deliberately catch every callback at our private earliest group.
            # Unrelated callbacks return immediately; any active stale selfie
            # session is cleared before the intended feature handles the click.
            app.add_handler(CallbackQueryHandler(_callback), group=_GROUP)
            app.add_handler(
                MessageHandler(filters.PHOTO | filters.Document.ALL, _image),
                group=_GROUP,
            )
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, _text),
                group=_GROUP,
            )
            app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = ["VERSION", "install_builder_hook"]
