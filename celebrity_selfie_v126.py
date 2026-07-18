# -*- coding: utf-8 -*-
"""Celebrity Selfie v126: one clean Telegram wizard, rewritten from scratch.

The legacy application has several historic AI-selfie callbacks whose callback
values are not consistent.  v126 does not guess those values: it inspects the
text of the button that was actually clicked.  A button containing both
"селфи" and "звезд/знаменит" always opens this wizard and the update is stopped
before any legacy callback or global error handler can run.

The module owns the Telegram conversation itself.  It reuses only the audited
v122 catalog/reference/generation primitives (50 RU + 50 US, Wikimedia packs,
custom references and resemblance refinement); no v123-v125 router is imported.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import celebrity_selfie_v122 as engine

VERSION = "v126-celebrity-selfie-clean-rewrite-2026-07-19"
_GROUP = -50000
_BUILDER_FLAG = "_celebrity_selfie_v126_builder"
_HANDLER_FLAG = "_celebrity_selfie_v126_handlers"
_ACTIVE_KEY = "_cs126_active"
_PATCH_LOCK: asyncio.Lock | None = None
log = logging.getLogger("gpt-bot.celebrity-selfie-v126")

KNOWN_ENTRY_CALLBACKS = {
    "act:fun:aiselfie",
    "pedit:aiselfie",
    "act:fun:selfie",
    "photo:aiselfie",
    "fun:aiselfie",
}

LEGACY_KEYS = {
    "photo_flow", "awaiting_photo_for", "retouch_prompt", "retouch_wait_text",
    "ai_selfie_flow", "aiselfie_flow", "selfie_flow", "ai_selfie_wait_prompt",
    "ai_selfie_prompt", "ai_selfie_preset", "photo_edit_mode",
    "pending_photo_action", "pending_photo_mode", "photo_mode", "photo_action",
    "awaiting_photo", "awaiting_image", "image_flow",
}


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _data(context: Any) -> dict[str, Any]:
    value = getattr(context, "user_data", None)
    return value if isinstance(value, dict) else {}


def _session(context: Any, create: bool = True) -> dict[str, Any]:
    try:
        value = engine._session(context, create=create)
    except TypeError:
        value = engine._session(context) if create else _data(context).get(engine._SESSION_KEY)
    return value if isinstance(value, dict) else {}


def _active(context: Any) -> bool:
    session = _session(context, create=False)
    return bool(_data(context).get(_ACTIVE_KEY)) and bool(session) and session.get("owner") == VERSION


def _clear_legacy_state(context: Any) -> None:
    data = _data(context)
    for key in tuple(LEGACY_KEYS):
        data.pop(key, None)
    for key in tuple(data):
        low = str(key).casefold()
        if key in (getattr(engine, "_SESSION_KEY", ""), _ACTIVE_KEY):
            continue
        if "aiselfie" in low or "ai_selfie" in low or "celebrity_selfie" in low:
            data.pop(key, None)


def _clear_all(context: Any) -> None:
    old = _session(context, create=False)
    with contextlib.suppress(Exception):
        engine._clear_session(context)
    data = _data(context)
    data.pop(_ACTIVE_KEY, None)
    _clear_legacy_state(context)
    if isinstance(old, dict):
        for key in ("work_dir", "session_dir", "temp_dir"):
            path = old.get(key)
            if path:
                with contextlib.suppress(Exception):
                    shutil.rmtree(str(path), ignore_errors=True)


def _new_session(context: Any) -> dict[str, Any]:
    _clear_all(context)
    session = _session(context)
    session.clear()
    session.update({
        "owner": VERSION,
        "state": "choose_user_photo",
        "created_at": time.time(),
    })
    _data(context)[_ACTIVE_KEY] = True
    _clear_legacy_state(context)
    return session


def _button_text(query: Any) -> str:
    """Return the text of the exact inline button whose callback was clicked."""
    data = str(getattr(query, "data", "") or "")
    message = getattr(query, "message", None)
    markup = getattr(message, "reply_markup", None)
    keyboard = getattr(markup, "inline_keyboard", None) or []
    for row in keyboard:
        for button in row:
            if str(getattr(button, "callback_data", "") or "") == data:
                return str(getattr(button, "text", "") or "")
    return ""


def _norm(value: str) -> str:
    value = str(value or "").casefold().replace("ё", "е")
    return " ".join(value.replace("—", " ").replace("-", " ").split())


def _is_entry(query: Any) -> bool:
    data = str(getattr(query, "data", "") or "")
    low_data = data.casefold()
    if data in KNOWN_ENTRY_CALLBACKS:
        return True
    if any(token in low_data for token in ("aiselfie", "ai_selfie", "ai-selfie", "selfie_star")):
        return True
    text = _norm(_button_text(query))
    return "селфи" in text and ("звезд" in text or "знаменит" in text)


def _is_ours_callback(query: Any) -> bool:
    data = str(getattr(query, "data", "") or "")
    return _is_entry(query) or data.startswith("cs126:") or data.startswith("celeb:")


def _kb(rows: list[list[tuple[str, str]]]):
    return engine._kb(rows)


def _photo_choice_kb(has_cached: bool):
    rows: list[list[tuple[str, str]]] = []
    if has_cached:
        rows.append([("✅ Использовать последнее фото", "cs126:use_last")])
    rows.append([("📤 Загрузить новое селфи", "cs126:upload")])
    rows.append([("❌ Отмена", "cs126:cancel")])
    return _kb(rows)


def _celebrity_menu_kb():
    # v122 owns the catalog menu and its callback vocabulary.  Calling the
    # factory is safe; its handlers are not installed and v126 delegates the
    # resulting celeb:* callbacks directly to the v122 implementation.
    return engine._main_menu_kb()


async def _reply(update: Any, text: str, reply_markup: Any = None) -> None:
    await update.effective_message.reply_text(text, reply_markup=reply_markup)


def _runtime_module() -> Any:
    with contextlib.suppress(Exception):
        return engine._runtime_module()
    return None


def _cached_photo(update: Any) -> bytes | None:
    module = _runtime_module()
    getter = getattr(module, "_get_cached_photo", None) if module is not None else None
    if callable(getter):
        with contextlib.suppress(Exception):
            raw = getter(update.effective_user.id)
            if raw:
                return bytes(raw)
    return None


def _cache_photo(update: Any, raw: bytes) -> None:
    module = _runtime_module()
    setter = getattr(module, "_cache_photo", None) if module is not None else None
    if callable(setter):
        with contextlib.suppress(Exception):
            setter(update.effective_user.id, raw)


def _fallback_store(update: Any, filename: str, raw: bytes) -> str:
    root = Path(os.environ.get("CELEBRITY_SESSION_ROOT", "/data/celebrity_sessions"))
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path("/tmp/celebrity_sessions")
        root.mkdir(parents=True, exist_ok=True)
    folder = root / str(update.effective_user.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{int(time.time())}_{uuid.uuid4().hex[:8]}_{filename}"
    path.write_bytes(raw)
    return str(path)


def _store_image(update: Any, session: dict[str, Any], filename: str, raw: bytes) -> str:
    with contextlib.suppress(Exception):
        path = engine._store_image(session, filename, raw)
        if path:
            return str(path)
    return _fallback_store(update, filename, raw)


def _normalize_image(raw: bytes) -> bytes | None:
    if not raw:
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.thumbnail((2048, 2048))
            out = BytesIO()
            image.save(out, format="JPEG", quality=94, optimize=True)
            value = out.getvalue()
            return value if len(value) >= 1024 else None
    except Exception as exc:
        log.warning("Image normalization failed: %s", exc)
    if raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw
    return None


async def _download_media(media: Any, context: Any) -> bytes:
    tg_file = None
    get_file = getattr(media, "get_file", None)
    if callable(get_file):
        with contextlib.suppress(Exception):
            tg_file = await get_file()
    if tg_file is None:
        tg_file = await context.bot.get_file(media.file_id)

    # PTB compatibility: current installations may accept BytesIO but not a
    # bytearray, while older builds expose only download_as_bytearray.
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

    try:
        out = bytearray()
        result = await tg_file.download_to_memory(out=out)
        raw = bytes(out)
        if not raw and result is not None and not isinstance(result, str):
            raw = bytes(result)
        if raw:
            return raw
    except Exception as exc:
        log.info("download_to_memory(bytearray) failed: %s", exc)

    method = getattr(tg_file, "download_as_bytearray", None)
    if callable(method):
        with contextlib.suppress(Exception):
            raw = bytes(await method())
            if raw:
                return raw

    method = getattr(tg_file, "download_to_drive", None)
    if callable(method):
        fd, path = tempfile.mkstemp(prefix="cs126-", suffix=".img")
        os.close(fd)
        try:
            await method(custom_path=path)
            raw = Path(path).read_bytes()
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
            name = str(getattr(document, "file_name", "") or "").casefold()
            if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp")):
                media = document
    if media is None:
        return None
    return _normalize_image(await _download_media(media, context))


async def _open(update: Any, context: Any) -> None:
    session = _new_session(context)
    cached = _cached_photo(update)
    if cached:
        session["state"] = "choose_user_photo"
        session["cached_candidate_path"] = _store_image(update, session, "cached_selfie.jpg", cached)
        await _reply(
            update,
            "📸 Точное AI-селфи со знаменитостью\n\n"
            "Выберите последнее фото или загрузите новое. Затем бот откроет отдельное меню "
            "100 публичных людей и возможность загрузить свои референсы.",
            _photo_choice_kb(True),
        )
    else:
        session["state"] = "await_user_photo"
        await _reply(
            update,
            "📸 Точное AI-селфи со знаменитостью\n\n"
            "Пришлите своё чёткое селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP. "
            "После загрузки сразу откроется выбор знаменитости.",
            _photo_choice_kb(False),
        )


async def _accept_user_photo(update: Any, context: Any, raw: bytes) -> None:
    session = _session(context)
    session["owner"] = VERSION
    session["user_photo_path"] = _store_image(update, session, "user_selfie.jpg", raw)
    session["state"] = "choose_celebrity"
    session.pop("cached_candidate_path", None)
    _data(context)[_ACTIVE_KEY] = True
    _clear_legacy_state(context)
    _cache_photo(update, raw)
    await _reply(
        update,
        "✅ Селфи получено. Теперь выберите знаменитость.\n\n"
        "Для человека из каталога используются 3–4 лицевых референса. Если его нет в базе, "
        "загрузите 1–4 фотографии вручную.",
        _celebrity_menu_kb(),
    )


def _direct_match(text: str) -> dict[str, Any] | None:
    normalized = engine._norm(text)
    if not normalized:
        return None
    candidates = engine.search_catalog(text, 10)
    for item in candidates:
        values = [
            str(item.get("display_name") or ""),
            str(item.get("sort_name") or ""),
            *[str(alias) for alias in item.get("aliases", [])],
        ]
        for value in values:
            alias = engine._norm(value)
            if alias and (alias in normalized or normalized in alias):
                return item
    return candidates[0] if len(candidates) == 1 else None


async def _prepare_catalog_person(update: Any, context: Any, item: dict[str, Any]) -> None:
    session = _session(context)
    session["owner"] = VERSION
    session["selected_celebrity_id"] = item.get("id")
    session["selected_celebrity_name"] = item.get("display_name")
    await _reply(
        update,
        f"⭐ Выбран: {item.get('display_name')}. Подготавливаю библиотечные референсы лица.",
    )
    try:
        await engine._prepare_library_refs(update, context, item)
    except Exception as exc:
        log.exception("Reference pack preparation failed for %s: %s", item.get("id"), exc)
        session["state"] = "choose_celebrity"
        await _reply(
            update,
            "Не удалось получить достаточный набор лицензированных референсов. "
            "Загрузите 1–4 чётких фотографии этого человека.",
            _kb([
                [("📤 Загрузить фото знаменитости", "celeb:custom_refs")],
                [("⬅️ К выбору", "celeb:menu")],
                [("❌ Отмена", "cs126:cancel")],
            ]),
        )


async def _delegate_custom_image(update: Any, context: Any, raw: bytes) -> None:
    global _PATCH_LOCK
    if _PATCH_LOCK is None:
        _PATCH_LOCK = asyncio.Lock()
    async with _PATCH_LOCK:
        original = getattr(engine, "_download_image_from_update")

        async def supplied(_: Any) -> bytes:
            return raw

        engine._download_image_from_update = supplied
        try:
            await engine._on_image(update, context)
        finally:
            engine._download_image_from_update = original


async def _callback(update: Any, context: Any) -> None:
    query = update.callback_query
    if query is None:
        return
    ours = _is_ours_callback(query)

    # Leaving the wizard by any unrelated inline button must never trap the
    # user. Clear state and let the intended legacy/menu handler process it.
    if not ours:
        if _active(context):
            _clear_all(context)
        return

    with contextlib.suppress(Exception):
        await query.answer()

    if _is_entry(query):
        try:
            await _open(update, context)
        except Exception as exc:
            log.exception("Clean Celebrity Selfie entry failed: %s", exc)
            # A clean upload prompt is the only visible fallback. Never emit a
            # generic global-error/recovery card.
            session = _new_session(context)
            session["state"] = "await_user_photo"
            await _reply(
                update,
                "📸 Точное AI-селфи со знаменитостью\n\nПришлите своё селфи обычной фотографией Telegram.",
                _photo_choice_kb(False),
            )
        _stop()

    data = str(getattr(query, "data", "") or "")
    if data in ("cs126:cancel", "celeb:cancel"):
        _clear_all(context)
        await _reply(update, "❌ Режим AI-селфи закрыт. Можно выбрать другую функцию в разделе «Развлечения».")
        _stop()

    if not _active(context):
        await _open(update, context)
        _stop()

    _clear_legacy_state(context)
    session = _session(context)

    if data == "cs126:upload":
        session["state"] = "await_user_photo"
        await _reply(
            update,
            "📤 Пришлите новое селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP.",
            _kb([[("❌ Отмена", "cs126:cancel")]]),
        )
        _stop()

    if data == "cs126:use_last":
        raw = _cached_photo(update)
        if not raw:
            path = session.get("cached_candidate_path")
            with contextlib.suppress(Exception):
                raw = Path(str(path)).read_bytes() if path else None
        if raw:
            await _accept_user_photo(update, context, raw)
        else:
            session["state"] = "await_user_photo"
            await _reply(update, "Последнее фото не найдено. Пришлите новое селфи.", _photo_choice_kb(False))
        _stop()

    # Every catalog/scene/refinement callback produced by v122 is executed
    # directly here. Its Telegram handlers are deliberately not installed.
    if data.startswith("celeb:"):
        try:
            await engine._on_callback(update, context)
        except Exception as exc:
            from telegram.ext import ApplicationHandlerStop
            if isinstance(exc, ApplicationHandlerStop):
                raise
            log.exception("v122 callback primitive failed data=%s: %s", data, exc)
            session["state"] = "choose_celebrity" if session.get("user_photo_path") else "await_user_photo"
            markup = _celebrity_menu_kb() if session.get("user_photo_path") else _photo_choice_kb(False)
            await _reply(update, "Не удалось выполнить этот пункт. Выберите действие ещё раз.", markup)
        _stop()

    _stop()


async def _image(update: Any, context: Any) -> None:
    if not _active(context):
        return
    _clear_legacy_state(context)
    session = _session(context)
    state = str(session.get("state") or "")
    try:
        raw = await _download_image(update, context)
        if not raw:
            await _reply(
                update,
                "Не удалось прочитать изображение. Отправьте его обычной фотографией Telegram "
                "или файлом JPG/PNG/WEBP.",
                _kb([[("❌ Отмена", "cs126:cancel")]]),
            )
            _stop()

        if state == "await_custom_refs":
            await _delegate_custom_image(update, context, raw)
            _stop()
        if state == "generating":
            await _reply(update, "⏳ Генерация уже выполняется. Дождитесь результата.")
            _stop()
        if state in ("await_user_photo", "choose_user_photo", ""):
            await _accept_user_photo(update, context, raw)
            _stop()

        await _reply(
            update,
            "Селфи пользователя уже сохранено. Для фотографий знаменитости нажмите "
            "«Загрузить фото знаменитости» в меню выбора.",
            _celebrity_menu_kb(),
        )
        _stop()
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Celebrity Selfie photo step failed state=%s: %s", state, exc)
        session["state"] = "choose_celebrity" if session.get("user_photo_path") else "await_user_photo"
        await _reply(
            update,
            "Фото не удалось обработать. Отправьте его ещё раз.",
            _celebrity_menu_kb() if session.get("user_photo_path") else _photo_choice_kb(False),
        )
        _stop()


async def _text(update: Any, context: Any) -> None:
    if not _active(context):
        return
    _clear_legacy_state(context)
    session = _session(context)
    text = str(getattr(update.effective_message, "text", "") or "").strip()
    state = str(session.get("state") or "")

    # Text reply-keyboard navigation should leave the wizard cleanly and then
    # continue to the normal section router.
    nav = _norm(text)
    if nav in {
        "развлечения", "назад", "меню ботов", "главное меню", "учеба",
        "работа бизнес", "работа/бизнес", "медицина", "движки", "о боте",
    }:
        _clear_all(context)
        return

    if state in ("await_user_photo", "choose_user_photo"):
        await _reply(update, "Сначала загрузите своё селфи.", _photo_choice_kb(bool(_cached_photo(update))))
        _stop()

    if state in ("choose_celebrity", "await_search"):
        match = _direct_match(text)
        if match:
            await _prepare_catalog_person(update, context, match)
        else:
            results = engine.search_catalog(text, 8)
            if results:
                await _reply(
                    update,
                    "Нашёл несколько вариантов. Выберите нужного человека:",
                    engine._search_results_kb(results),
                )
            else:
                await _reply(
                    update,
                    "В каталоге совпадений нет. Загрузите 1–4 фотографии нужного человека.",
                    _kb([
                        [("📤 Загрузить фото знаменитости", "celeb:custom_refs")],
                        [("⬅️ К выбору", "celeb:menu")],
                        [("❌ Отмена", "cs126:cancel")],
                    ]),
                )
        _stop()

    try:
        await engine._on_text(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("v122 text primitive failed state=%s: %s", state, exc)
        await _reply(update, "Продолжите текущий шаг кнопками меню.", _celebrity_menu_kb())
    _stop()


async def _diag(update: Any, context: Any) -> None:
    session = _session(context, create=False)
    await _reply(
        update,
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if _active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        f"callback_priority={_GROUP}\n"
        f"photo_priority={_GROUP}\n"
        "entry_detection=callback+clicked_button_text\n"
        "telegram_photo=enabled\n"
        "catalog=100\n"
        "legacy_routers=not_installed",
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
            # Catch every callback only to inspect the clicked button text. For
            # unrelated buttons the handler returns and the normal router runs.
            app.add_handler(CallbackQueryHandler(_callback), group=_GROUP)
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _image), group=_GROUP)
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=_GROUP)
            app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = ["VERSION", "install_builder_hook"]
