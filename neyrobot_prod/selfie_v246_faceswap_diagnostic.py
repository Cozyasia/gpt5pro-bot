# -*- coding: utf-8 -*-
"""Isolated two-photo PiAPI face-swap diagnostic for Entertainment mode.

This flow deliberately bypasses Gemini, celebrity references, scene generation,
payment guards and the production selfie state machine. It answers one question:
can the configured PiAPI/Qubico face-swap transport replace the face from photo 1
(source) onto photo 2 (target)?
"""
from __future__ import annotations

import contextlib
import hashlib
import sys
import time
import uuid
from typing import Any

VERSION = "v247-visible-faceswap-diagnostic-2026-08-07"
STATE = "faceswap_diag_state"
SOURCE = "faceswap_diag_source"
TARGET = "faceswap_diag_target"


def _log(message: str, *args: Any) -> None:
    try:
        rendered = message % args if args else message
    except Exception:
        rendered = f"{message} {args!r}"
    print(f"[neyrobot-prod] FACE_SWAP_DIAG {rendered}", flush=True)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw)).hexdigest()[:16]


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


def _reset(context: Any) -> None:
    for key in (STATE, SOURCE, TARGET):
        context.user_data.pop(key, None)


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
    _reset(context)
    context.user_data[STATE] = "source"
    await message.reply_text(
        "🧪 Отдельный тест Face Swap\n\n"
        "Шаг 1/2: пришлите фотографию-источник. Лицо с неё должно быть перенесено. "
        "Лучше: один человек, анфас, без очков, лицо полностью видно.\n\n"
        "Этот тест не запускает Gemini, не выбирает героя и не меняет основную функцию AI-селфи.",
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
    _reset(context)
    if message is not None:
        await message.reply_text("Тест Face Swap отменён.")
    raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    state = str(context.user_data.get(STATE) or "")
    if state not in {"source", "target"}:
        return
    message = getattr(update, "effective_message", None)
    if message is None:
        return
    raw, _url = await base._download_photo_message(message)
    if not raw:
        await message.reply_text("❌ Не удалось прочитать изображение. Пришлите фото как изображение или JPG/PNG-документ.")
        raise ApplicationHandlerStop

    trace = uuid.uuid4().hex[:12]
    try:
        info = _describe(raw)
    except Exception as exc:
        _log("trace=%s stage=input_invalid state=%s error=%r", trace, state, exc)
        await message.reply_text(f"❌ Файл не распознан как изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    _log("trace=%s stage=input_received role=%s info=%r", trace, state, info)
    if state == "source":
        context.user_data[SOURCE] = bytes(raw)
        context.user_data[STATE] = "target"
        warning = "" if info["faces"] else "\n⚠️ Наш локальный детектор не увидел лицо, но тест можно продолжить."
        await message.reply_text(
            "✅ Фото-источник принято.\n"
            f"Размер: {info['dims']}, найдено лиц: {info['faces']}."
            f"{warning}\n\nШаг 2/2: пришлите целевую фотографию. На ней лицо первого/главного человека будет заменено лицом из фото 1."
        )
        raise ApplicationHandlerStop

    source = bytes(context.user_data.get(SOURCE) or b"")
    if len(source) < 1024:
        _reset(context)
        await message.reply_text("❌ Источник лица потерян. Запустите тест заново кнопкой «Тест Face Swap».")
        raise ApplicationHandlerStop

    context.user_data[TARGET] = bytes(raw)
    context.user_data[STATE] = "running"
    source_info = _describe(source)
    target_info = info
    started = time.monotonic()
    _log("trace=%s stage=swap_start source=%r target=%r transport=%s", trace, source_info, target_info, getattr(v237._piapi_single_face_swap, "__module__", "unknown"))
    await message.reply_text(
        "⏳ Запускаю изолированный PiAPI Face Swap.\n"
        f"Код теста: {trace}. В Render ищите FACE_SWAP_DIAG и этот код."
    )
    try:
        result = await v237._piapi_single_face_swap(bytes(raw), source, _log)
        result_info = _describe(result)
        elapsed = time.monotonic() - started
        _log("trace=%s stage=swap_success elapsed=%.2f result=%r changed_from_target=%s", trace, elapsed, result_info, _sha(result) != _sha(raw))
        await message.reply_document(
            document=result,
            filename=f"faceswap_diag_{trace}.jpg",
            caption=(
                "✅ Изолированный Face Swap выполнен.\n"
                f"Код: {trace}\n"
                f"Время: {elapsed:.1f} сек.\n"
                f"Источник: {source_info['dims']}, лиц {source_info['faces']}\n"
                f"Цель: {target_info['dims']}, лиц {target_info['faces']}\n"
                f"Результат: {result_info['dims']}, лиц {result_info['faces']}"
            ),
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        _log("trace=%s stage=swap_failed elapsed=%.2f error_type=%s error=%r", trace, elapsed, type(exc).__name__, str(exc)[:1600])
        await message.reply_text(
            "❌ Изолированный Face Swap завершился ошибкой.\n"
            f"Код: {trace}\n"
            f"Этап: только PiAPI, без Gemini и без основной логики селфи.\n"
            f"Причина: {type(exc).__name__}: {str(exc)[:700]}"
        )
    finally:
        _reset(context)
    raise ApplicationHandlerStop


def _append_diag_button(markup: Any) -> Any:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [list(row) for row in getattr(markup, "inline_keyboard", [])]
    if not any(getattr(button, "callback_data", "") == "fsdiag:start" for row in rows for button in row):
        rows.append([InlineKeyboardButton("🧪 Тест Face Swap", callback_data="fsdiag:start")])
    return InlineKeyboardMarkup(rows)


def patch_main_keyboard() -> bool:
    """Patch the AI-selfie internal menu and keep patching if runtime owner code replaces it."""
    from neyrobot_prod import celebrity_selfie as base

    current = getattr(base, "_main_kb", None)
    if not callable(current):
        return False
    if getattr(current, "_faceswap_diag_v247", False):
        return True

    original = current

    def wrapped(mod: Any):
        return _append_diag_button(original(mod))

    setattr(wrapped, "_faceswap_diag_v247", True)
    base._main_kb = wrapped
    _log("stage=ai_selfie_menu_patch status=installed version=%s", VERSION)
    return True


def patch_runtime_entertainment_menu() -> bool:
    """Patch main.py Entertainment menu, which is the screen users actually open first."""
    mod = sys.modules.get("__main__") or sys.modules.get("main")
    if mod is None:
        return False
    current = getattr(mod, "_mode_kb", None)
    if not callable(current):
        return False
    if getattr(current, "_faceswap_diag_v247", False):
        return True

    original = current

    def wrapped(key: str):
        markup = original(key)
        if str(key) == "fun":
            return _append_diag_button(markup)
        return markup

    setattr(wrapped, "_faceswap_diag_v247", True)
    setattr(mod, "_mode_kb", wrapped)
    _log("stage=entertainment_menu_patch status=installed version=%s", VERSION)
    return True


def bind_application(app: Any) -> bool:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    flag = "_faceswap_diag_v247_bound"
    if getattr(app, flag, False):
        return True
    patch_main_keyboard()
    patch_runtime_entertainment_menu()
    app.add_handler(CommandHandler("faceswap_test", start), group=-7000)
    app.add_handler(CallbackQueryHandler(start, pattern=r"^fsdiag:start$"), group=-7000)
    app.add_handler(CallbackQueryHandler(cancel, pattern=r"^fsdiag:cancel$"), group=-7000)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media), group=-6999)
    setattr(app, flag, True)
    _log("stage=bind status=ok version=%s", VERSION)
    return True


__all__ = [
    "VERSION", "start", "cancel", "media", "patch_main_keyboard",
    "patch_runtime_entertainment_menu", "bind_application"
]
