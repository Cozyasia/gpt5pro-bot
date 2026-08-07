# -*- coding: utf-8 -*-
"""Isolated two-photo PiAPI face-swap diagnostic for Entertainment mode.

This flow deliberately bypasses Gemini, celebrity references, scene generation,
payment guards and the production selfie state machine. It also bypasses the
mutable v237 face-swap pointer so runtime owner/fallback patches cannot change
which transport the diagnostic is exercising.
"""
from __future__ import annotations

import contextlib
import hashlib
import sys
import time
import uuid
from typing import Any

VERSION = "v248-pure-piapi-faceswap-diagnostic-2026-08-07"
STATE = "faceswap_diag_state"
SOURCE = "faceswap_diag_source"
TARGET = "faceswap_diag_target"
_SESSIONS: dict[tuple[int, int], dict[str, Any]] = {}


def _log(message: str, *args: Any) -> None:
    try:
        rendered = message % args if args else message
    except Exception:
        rendered = f"{message} {args!r}"
    print(f"[neyrobot-prod] FACE_SWAP_DIAG {rendered}", flush=True)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw)).hexdigest()[:16]


def _key(update: Any) -> tuple[int, int]:
    user = getattr(update, "effective_user", None)
    chat = getattr(update, "effective_chat", None)
    return (int(getattr(chat, "id", 0) or 0), int(getattr(user, "id", 0) or 0))


def _describe(raw: bytes) -> dict[str, Any]:
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    image = v237._image(raw)
    faces = v237._detect_faces(image)
    return {
        "bytes": len(raw),
        "dims": f"{image.size[0]}x{image.size[1]}",
        "sha": _sha(raw),
        "faces": len(faces),
        "boxes": faces[:5],
    }


async def _download_image_message(message: Any) -> bytes:
    """Download Telegram image directly; do not call production photo handlers."""
    candidate = None
    photos = getattr(message, "photo", None) or []
    if photos:
        candidate = photos[-1]
    else:
        doc = getattr(message, "document", None)
        mime = str(getattr(doc, "mime_type", "") or "").lower() if doc is not None else ""
        name = str(getattr(doc, "file_name", "") or "").lower() if doc is not None else ""
        if doc is not None and (mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp"))):
            candidate = doc
    if candidate is None:
        return b""
    tg_file = await candidate.get_file()
    raw = await tg_file.download_as_bytearray()
    return bytes(raw or b"")


def _reset(update: Any, context: Any) -> None:
    for key in (STATE, SOURCE, TARGET):
        context.user_data.pop(key, None)
    _SESSIONS.pop(_key(update), None)


def _session(update: Any, context: Any) -> dict[str, Any]:
    key = _key(update)
    session = _SESSIONS.setdefault(key, {})
    # Mirror state into context.user_data only for visibility/debugging. The
    # global session is authoritative so other handlers cannot accidentally
    # clear the diagnostic by resetting transient production state.
    state = str(session.get("state") or context.user_data.get(STATE) or "")
    if state:
        session["state"] = state
        context.user_data[STATE] = state
    return session


async def start(update: Any, context: Any) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    message = getattr(update, "effective_message", None)
    if query is not None:
        with contextlib.suppress(Exception):
            await query.answer()
        message = query.message
    if message is None:
        return
    _reset(update, context)
    session = _session(update, context)
    session["state"] = "source"
    context.user_data[STATE] = "source"
    _log("stage=session_start key=%s version=%s", _key(update), VERSION)
    await message.reply_text(
        "🧪 Отдельный тест Face Swap\n\n"
        "Шаг 1/2: пришлите фотографию-источник. Лицо с неё должно быть перенесено. "
        "Лучше: один человек, анфас, без очков, лицо полностью видно.\n\n"
        "Этот тест идёт напрямую через PiAPI/Qubico: без Gemini, без героя, без AI-селфи и без production face-swap wrapper.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить тест", callback_data="fsdiag:cancel")]]),
    )
    raise ApplicationHandlerStop


async def cancel(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    if query is not None:
        with contextlib.suppress(Exception):
            await query.answer()
        message = query.message
    else:
        message = getattr(update, "effective_message", None)
    _log("stage=session_cancel key=%s", _key(update))
    _reset(update, context)
    if message is not None:
        await message.reply_text("Тест Face Swap отменён.")
    raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as v243

    session = _session(update, context)
    state = str(session.get("state") or "")
    if state not in {"source", "target"}:
        return
    message = getattr(update, "effective_message", None)
    if message is None:
        raise ApplicationHandlerStop

    trace = uuid.uuid4().hex[:12]
    _log("trace=%s stage=handler_enter key=%s state=%s", trace, _key(update), state)
    try:
        raw = await _download_image_message(message)
    except Exception as exc:
        _log("trace=%s stage=telegram_download_failed state=%s error_type=%s error=%r", trace, state, type(exc).__name__, str(exc)[:1000])
        await message.reply_text(f"❌ Не удалось скачать изображение из Telegram: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    if len(raw) < 1024:
        _log("trace=%s stage=telegram_download_empty state=%s bytes=%s", trace, state, len(raw))
        await message.reply_text("❌ Не удалось прочитать изображение. Пришлите его как обычное фото или JPG/PNG-документ.")
        raise ApplicationHandlerStop

    try:
        info = _describe(raw)
    except Exception as exc:
        _log("trace=%s stage=input_invalid state=%s bytes=%s error_type=%s error=%r", trace, state, len(raw), type(exc).__name__, str(exc)[:1000])
        await message.reply_text(f"❌ Файл скачан, но не открылся как изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    _log("trace=%s stage=input_received role=%s info=%r", trace, state, info)
    if state == "source":
        session["source"] = bytes(raw)
        session["source_info"] = info
        session["state"] = "target"
        context.user_data[SOURCE] = bytes(raw)
        context.user_data[STATE] = "target"
        warning = "" if info["faces"] else "\n⚠️ Локальный OpenCV-детектор лицо не увидел. Это не блокирует прямой тест PiAPI."
        await message.reply_text(
            "✅ Фото-источник принято.\n"
            f"Размер: {info['dims']}, локально найдено лиц: {info['faces']}."
            f"{warning}\n\nШаг 2/2: пришлите целевую фотографию. На ней лицо главного человека должно быть заменено лицом из фото 1."
        )
        raise ApplicationHandlerStop

    source = bytes(session.get("source") or b"")
    if len(source) < 1024:
        _log("trace=%s stage=source_missing key=%s", trace, _key(update))
        _reset(update, context)
        await message.reply_text("❌ Источник лица потерян. Запустите тест заново кнопкой «Тест Face Swap».")
        raise ApplicationHandlerStop

    session["target"] = bytes(raw)
    session["state"] = "running"
    context.user_data[TARGET] = bytes(raw)
    context.user_data[STATE] = "running"
    source_info = session.get("source_info") or _describe(source)
    target_info = info
    started = time.monotonic()
    transport_name = f"{v243.resilient_piapi_single_face_swap.__module__}.{v243.resilient_piapi_single_face_swap.__name__}"
    _log("trace=%s stage=swap_start source=%r target=%r transport=%s version=%s", trace, source_info, target_info, transport_name, getattr(v243, "VERSION", "unknown"))
    await message.reply_text(
        "⏳ Запускаю ЧИСТЫЙ PiAPI Face Swap.\n"
        f"Код теста: {trace}. В Render ищите FACE_SWAP_DIAG и этот код.\n"
        "Основные обработчики фото сейчас не участвуют."
    )
    try:
        result = await v243.resilient_piapi_single_face_swap(bytes(raw), source, _log)
        result_info = _describe(result)
        elapsed = time.monotonic() - started
        _log("trace=%s stage=swap_success elapsed=%.2f result=%r changed_from_target=%s", trace, elapsed, result_info, _sha(result) != _sha(raw))
        await message.reply_document(
            document=result,
            filename=f"faceswap_diag_{trace}.jpg",
            caption=(
                "✅ Чистый PiAPI Face Swap выполнен.\n"
                f"Код: {trace}\n"
                f"Время: {elapsed:.1f} сек.\n"
                f"Источник: {source_info['dims']}, локально лиц {source_info['faces']}\n"
                f"Цель: {target_info['dims']}, локально лиц {target_info['faces']}\n"
                f"Результат: {result_info['dims']}, локально лиц {result_info['faces']}"
            ),
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        _log("trace=%s stage=swap_failed elapsed=%.2f error_type=%s error=%r", trace, elapsed, type(exc).__name__, str(exc)[:2200])
        await message.reply_text(
            "❌ Чистый PiAPI Face Swap завершился ошибкой.\n"
            f"Код: {trace}\n"
            f"Время: {elapsed:.1f} сек.\n"
            "Этап: только прямой PiAPI/Qubico transport — без Gemini и без production wrapper.\n"
            f"Причина: {type(exc).__name__}: {str(exc)[:900]}"
        )
    finally:
        _reset(update, context)
    raise ApplicationHandlerStop


def _append_diag_button(markup: Any) -> Any:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [list(row) for row in getattr(markup, "inline_keyboard", [])]
    if not any(getattr(button, "callback_data", "") == "fsdiag:start" for row in rows for button in row):
        rows.append([InlineKeyboardButton("🧪 Тест Face Swap", callback_data="fsdiag:start")])
    return InlineKeyboardMarkup(rows)


def patch_main_keyboard() -> bool:
    from neyrobot_prod import celebrity_selfie as base

    current = getattr(base, "_main_kb", None)
    if not callable(current):
        return False
    if getattr(current, "_faceswap_diag_v248", False):
        return True
    original = current

    def wrapped(mod: Any):
        return _append_diag_button(original(mod))

    setattr(wrapped, "_faceswap_diag_v248", True)
    base._main_kb = wrapped
    _log("stage=ai_selfie_menu_patch status=installed version=%s", VERSION)
    return True


def patch_runtime_entertainment_menu() -> bool:
    mod = sys.modules.get("__main__") or sys.modules.get("main")
    if mod is None:
        return False
    current = getattr(mod, "_mode_kb", None)
    if not callable(current):
        return False
    if getattr(current, "_faceswap_diag_v248", False):
        return True
    original = current

    def wrapped(key: str):
        markup = original(key)
        if str(key) == "fun":
            return _append_diag_button(markup)
        return markup

    setattr(wrapped, "_faceswap_diag_v248", True)
    setattr(mod, "_mode_kb", wrapped)
    _log("stage=entertainment_menu_patch status=installed version=%s", VERSION)
    return True


def bind_application(app: Any) -> bool:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    flag = "_faceswap_diag_v248_bound"
    if getattr(app, flag, False):
        return True
    patch_main_keyboard()
    patch_runtime_entertainment_menu()
    # Very early unique groups: while a diagnostic session is active, its photos
    # must be consumed before any generic photo/AI-selfie/medical handlers.
    app.add_handler(CommandHandler("faceswap_test", start), group=-900001)
    app.add_handler(CallbackQueryHandler(start, pattern=r"^fsdiag:start$"), group=-900001)
    app.add_handler(CallbackQueryHandler(cancel, pattern=r"^fsdiag:cancel$"), group=-900001)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media), group=-900000)
    setattr(app, flag, True)
    _log("stage=bind status=ok version=%s groups=-900001/-900000", VERSION)
    return True


__all__ = [
    "VERSION", "start", "cancel", "media", "patch_main_keyboard",
    "patch_runtime_entertainment_menu", "bind_application"
]
