# -*- coding: utf-8 -*-
"""Isolated PiAPI face-swap diagnostic for Entertainment mode.

The user-pair test bypasses Gemini, scene generation and production selfie
wrappers. If that fails, an explicit provider-control button can run PiAPI's own
documented sample pair. That separates provider/account failures from failures
caused by the user's source/target photos.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import sys
import time
import uuid
from typing import Any

import httpx

VERSION = "v250-piapi-control-probe-2026-08-07"
STATE = "faceswap_diag_state"
SOURCE = "faceswap_diag_source"
TARGET = "faceswap_diag_target"
_SESSIONS: dict[tuple[int, int], dict[str, Any]] = {}

# Current official PiAPI Faceswap documentation example pair.
_CONTROL_TARGET = "https://i.ibb.co/LnLYwhR/66f41e64b1922.jpg"
_CONTROL_SWAP = "https://i.ibb.co/m9BFL9J/ad61a39afd9079e57a5908c0bd9dd995.jpg"


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
    return {"bytes": len(raw), "dims": f"{image.size[0]}x{image.size[1]}", "sha": _sha(raw), "faces": len(faces), "boxes": faces[:5]}


async def _download_image_message(message: Any) -> bytes:
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
    state = str(session.get("state") or context.user_data.get(STATE) or "")
    if state:
        session["state"] = state
        context.user_data[STATE] = state
    return session


def _control_keyboard() -> Any:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Проверить PiAPI на эталонных фото", callback_data="fsdiag:control")],
        [InlineKeyboardButton("🔁 Новый тест с моими фото", callback_data="fsdiag:start")],
    ])


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
        "Тест идёт напрямую через PiAPI/Qubico: без Gemini, героя и production face-swap wrapper.",
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


async def provider_control(update: Any, context: Any) -> None:
    """Run the exact request shape and sample URLs from PiAPI docs, only on click."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as v249

    query = getattr(update, "callback_query", None)
    message = getattr(update, "effective_message", None)
    if query is not None:
        with contextlib.suppress(Exception):
            await query.answer()
        message = query.message
    if message is None:
        raise ApplicationHandlerStop

    trace = uuid.uuid4().hex[:12]
    key = str(os.getenv("PIAPI_API_KEY") or "").strip()
    if not key:
        await message.reply_text("❌ PIAPI_API_KEY отсутствует в окружении.")
        raise ApplicationHandlerStop

    await message.reply_text(
        "🧪 Запускаю контрольный запрос PiAPI на эталонных фото из официальной документации.\n"
        f"Код: {trace}. Это отдельный платный API-вызов Face Swap."
    )
    _log("trace=%s stage=control_start target=%s swap=%s", trace, _CONTROL_TARGET, _CONTROL_SWAP)
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    body = {"model": "Qubico/image-toolkit", "task_type": "face-swap", "input": {"target_image": _CONTROL_TARGET, "swap_image": _CONTROL_SWAP}}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
            response = await client.post(v237.PIAPI_TASK_URL, headers=headers, json=body)
            try:
                payload = response.json()
            except Exception:
                payload = None
            failure = v249._provider_failure(payload)
            preview = (response.text or "")[:1600].replace("\n", " ")
            _log("trace=%s stage=control_create http=%s failure=%s body=%s", trace, response.status_code, failure or "-", preview)
            if failure:
                raise RuntimeError(f"CONTROL provider failure: HTTP {response.status_code} | {failure}")
            if response.status_code >= 400 or not isinstance(payload, dict):
                raise RuntimeError(f"CONTROL create failed: HTTP {response.status_code}: {preview}")
            data = payload.get("data") if isinstance(payload, dict) else None
            task_id = str((data or {}).get("task_id") or "").strip()
            if not task_id:
                raise RuntimeError(f"CONTROL no task_id: {preview}")
            deadline = asyncio.get_running_loop().time() + 120.0
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(2.0)
                check = await client.get(f"{v237.PIAPI_TASK_URL}/{task_id}", headers={"x-api-key": key})
                try:
                    current = check.json()
                except Exception:
                    current = None
                failure = v249._provider_failure(current)
                if failure:
                    raise RuntimeError(f"CONTROL provider failure while polling: HTTP {check.status_code} | {failure}")
                pdata = current.get("data") if isinstance(current, dict) else None
                status = str((pdata or {}).get("status") or "").lower()
                _log("trace=%s stage=control_poll task_id=%s http=%s status=%s", trace, task_id, check.status_code, status)
                if status in {"completed", "success", "succeeded"}:
                    url = v249._output_url(current)
                    elapsed = time.monotonic() - started
                    _log("trace=%s stage=control_success task_id=%s elapsed=%.2f output=%s", trace, task_id, elapsed, url)
                    await message.reply_text(
                        "✅ Эталонный PiAPI Face Swap работает.\n"
                        f"Код: {trace}\nВремя: {elapsed:.1f} сек.\n\n"
                        "Значит ключ, баланс и сам сервис исправны; проблема относится к нашим входным изображениям/детекции лица."
                    )
                    raise ApplicationHandlerStop
            raise TimeoutError("CONTROL PiAPI task timed out after 120 sec")
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        elapsed = time.monotonic() - started
        _log("trace=%s stage=control_failed elapsed=%.2f error=%r", trace, elapsed, str(exc)[:2200])
        await message.reply_text(
            "❌ Эталонный запрос PiAPI тоже не прошёл.\n"
            f"Код: {trace}\nВремя: {elapsed:.1f} сек.\nПричина: {type(exc).__name__}: {str(exc)[:1200]}\n\n"
            "Это уже указывает на PiAPI/Qubico, аккаунт/доступ модели или провайдерский backend, а не на Gemini и не на наши фотографии."
        )
    raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as v249

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
        _log("trace=%s stage=telegram_download_failed state=%s error=%r", trace, state, str(exc)[:1000])
        await message.reply_text(f"❌ Не удалось скачать изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop
    if len(raw) < 1024:
        await message.reply_text("❌ Не удалось прочитать изображение. Пришлите обычное фото или JPG/PNG-документ.")
        raise ApplicationHandlerStop
    try:
        info = _describe(raw)
    except Exception as exc:
        await message.reply_text(f"❌ Файл не открылся как изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop
    _log("trace=%s stage=input_received role=%s info=%r", trace, state, info)
    if state == "source":
        session["source"] = bytes(raw)
        session["source_info"] = info
        session["state"] = "target"
        context.user_data[SOURCE] = bytes(raw)
        context.user_data[STATE] = "target"
        warning = "" if info["faces"] else "\n⚠️ Локальный OpenCV-детектор лицо не увидел. Это не блокирует прямой PiAPI-тест."
        await message.reply_text(
            "✅ Фото-источник принято.\n"
            f"Размер: {info['dims']}, локально найдено лиц: {info['faces']}."
            f"{warning}\n\nШаг 2/2: пришлите целевую фотографию."
        )
        raise ApplicationHandlerStop

    source = bytes(session.get("source") or b"")
    if len(source) < 1024:
        _reset(update, context)
        await message.reply_text("❌ Источник лица потерян. Запустите тест заново.")
        raise ApplicationHandlerStop
    session["state"] = "running"
    source_info = session.get("source_info") or _describe(source)
    started = time.monotonic()
    _log("trace=%s stage=swap_start source=%r target=%r transport=%s version=%s", trace, source_info, info, v249.resilient_piapi_single_face_swap.__name__, getattr(v249, "VERSION", "unknown"))
    await message.reply_text(
        "⏳ Запускаю ЧИСТЫЙ PiAPI Face Swap.\n"
        f"Код теста: {trace}. В Render ищите FACE_SWAP_DIAG и этот код."
    )
    try:
        result = await v249.resilient_piapi_single_face_swap(bytes(raw), source, _log)
        result_info = _describe(result)
        elapsed = time.monotonic() - started
        _log("trace=%s stage=swap_success elapsed=%.2f result=%r", trace, elapsed, result_info)
        await message.reply_document(document=result, filename=f"faceswap_diag_{trace}.jpg", caption=f"✅ Чистый PiAPI Face Swap выполнен. Код: {trace}. Время: {elapsed:.1f} сек.")
    except Exception as exc:
        elapsed = time.monotonic() - started
        _log("trace=%s stage=swap_failed elapsed=%.2f error_type=%s error=%r", trace, elapsed, type(exc).__name__, str(exc)[:2600])
        await message.reply_text(
            "❌ Чистый PiAPI Face Swap завершился ошибкой.\n"
            f"Код: {trace}\nВремя: {elapsed:.1f} сек.\n"
            f"Причина: {type(exc).__name__}: {str(exc)[:1400]}\n\n"
            "Теперь можно отделить ошибку конкретных фото от ошибки самого провайдера:",
            reply_markup=_control_keyboard(),
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
    if getattr(current, "_faceswap_diag_v250", False):
        return True
    original = current
    def wrapped(mod: Any):
        return _append_diag_button(original(mod))
    setattr(wrapped, "_faceswap_diag_v250", True)
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
    if getattr(current, "_faceswap_diag_v250", False):
        return True
    original = current
    def wrapped(key: str):
        markup = original(key)
        if str(key) == "fun":
            return _append_diag_button(markup)
        return markup
    setattr(wrapped, "_faceswap_diag_v250", True)
    setattr(mod, "_mode_kb", wrapped)
    return True


def bind_application(app: Any) -> bool:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    flag = "_faceswap_diag_v250_bound"
    if getattr(app, flag, False):
        return True
    patch_main_keyboard()
    patch_runtime_entertainment_menu()
    app.add_handler(CommandHandler("faceswap_test", start), group=-900001)
    app.add_handler(CallbackQueryHandler(start, pattern=r"^fsdiag:start$"), group=-900001)
    app.add_handler(CallbackQueryHandler(cancel, pattern=r"^fsdiag:cancel$"), group=-900001)
    app.add_handler(CallbackQueryHandler(provider_control, pattern=r"^fsdiag:control$"), group=-900001)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media), group=-900000)
    setattr(app, flag, True)
    _log("stage=bind status=ok version=%s groups=-900001/-900000", VERSION)
    return True


__all__ = ["VERSION", "start", "cancel", "provider_control", "media", "patch_main_keyboard", "patch_runtime_entertainment_menu", "bind_application"]
