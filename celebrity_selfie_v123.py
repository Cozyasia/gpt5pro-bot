# -*- coding: utf-8 -*-
"""v123 routing hardening for Celebrity Selfie.

The v122 feature is complete, but the legacy photo workshop can still receive
callbacks, photos and text before/after it. This overlay makes Celebrity
Selfie an exclusive wizard while its session is active and gives its entry
callback the highest application priority.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from typing import Any

import celebrity_selfie_v122 as base

VERSION = "v123-celebrity-selfie-exclusive-flow-2026-07-19"
_BUILDER_FLAG = "_celebrity_selfie_v123_builder"
_HANDLER_FLAG = "_celebrity_selfie_v123_handlers"
_RUNTIME_STARTED = False
log = logging.getLogger("gpt-bot.celebrity-selfie-v123")

_LEGACY_FLOW_KEYS = {
    "photo_flow", "awaiting_photo_for", "retouch_prompt", "retouch_wait_text",
    "ai_selfie_flow", "aiselfie_flow", "selfie_flow", "ai_selfie_wait_prompt",
    "ai_selfie_prompt", "ai_selfie_preset", "photo_edit_mode",
    "pending_photo_action", "pending_photo_mode",
}


def _clear_legacy_flows(context: Any) -> None:
    data = getattr(context, "user_data", None)
    if not isinstance(data, dict):
        return
    for key in tuple(_LEGACY_FLOW_KEYS):
        data.pop(key, None)
    for key in tuple(data):
        low = str(key).casefold()
        if ("selfie" in low or "aiselfie" in low) and key != base._SESSION_KEY:
            data.pop(key, None)


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _cached_photo(update: Any) -> bytes | None:
    mod = base._runtime_module()
    getter = getattr(mod, "_get_cached_photo", None) if mod is not None else None
    if callable(getter):
        with contextlib.suppress(Exception):
            raw = getter(update.effective_user.id)
            if raw:
                return bytes(raw)
    return None


async def _accept_user_photo(update: Any, context: Any, raw: bytes) -> None:
    session = base._session(context)
    session["user_photo_path"] = base._store_image(session, "user_selfie.jpg", raw)
    session["state"] = "choose_celebrity"
    mod = base._runtime_module()
    cache = getattr(mod, "_cache_photo", None) if mod is not None else None
    if callable(cache):
        with contextlib.suppress(Exception):
            cache(update.effective_user.id, raw)
    await update.effective_message.reply_text(
        "✅ Селфи сохранено. Теперь выберите, с кем сделать AI-фото.\n\n"
        "Для людей из базы бот использует 3–4 отдельных референса. Если нужного человека нет, загрузите его фотографии вручную.",
        reply_markup=base._main_menu_kb(),
    )


async def _open_entry(update: Any, context: Any) -> None:
    _clear_legacy_flows(context)
    base._clear_session(context)
    session = base._session(context)
    cached = _cached_photo(update)
    if cached:
        session["cached_candidate_path"] = base._store_image(session, "cached_selfie.jpg", cached)
        session["state"] = "choose_user_photo"
        await update.effective_message.reply_text(
            "📸 Точное AI-селфи со знаменитостью\n\n"
            "Выберите исходное фото. После этого откроется отдельное меню выбора знаменитости, поиска по имени или загрузки собственных референсов.",
            reply_markup=base._kb([
                [("✅ Использовать последнее фото", "celeb:use_cached")],
                [("📤 Загрузить новое селфи", "celeb:upload_user")],
                [("❌ Отмена", "celeb:cancel")],
            ]),
        )
    else:
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text(
            "📸 Точное AI-селфи со знаменитостью\n\n"
            "Пришлите своё чёткое фото. Сразу после загрузки я открою новое меню: русские знаменитости, американские знаменитости, поиск по имени или свои референсы.",
            reply_markup=base._kb([[("❌ Отмена", "celeb:cancel")]]),
        )


def _direct_catalog_match(text: str) -> dict[str, Any] | None:
    """Resolve phrases such as 'селфи с Романом Абрамовичем'."""
    normalized = base._norm(text)
    if not normalized:
        return None
    candidates = base.search_catalog(text, 8)
    for item in candidates:
        values = [
            str(item.get("display_name") or ""),
            str(item.get("sort_name") or ""),
            *[str(x) for x in item.get("aliases", [])],
        ]
        for value in values:
            alias = base._norm(value)
            if alias and (alias in normalized or normalized in alias):
                return item
    return candidates[0] if len(candidates) == 1 else None


async def _safe_callback(update: Any, context: Any) -> None:
    query = update.callback_query
    data = str(getattr(query, "data", "") or "")
    if not (data == "act:fun:aiselfie" or data.startswith("celeb:")):
        return
    try:
        with contextlib.suppress(Exception):
            await query.answer()
        _clear_legacy_flows(context)
        if data == "act:fun:aiselfie":
            await _open_entry(update, context)
            _stop()

        if not base._active(context):
            await update.effective_message.reply_text(
                "Эта кнопка относится к завершённой сессии. Откройте режим заново.",
                reply_markup=base._kb([[('📸 Открыть AI-селфи', 'act:fun:aiselfie')]]),
            )
            _stop()

        session = base._session(context)
        if data == "celeb:use_cached":
            raw = base._read_path(session.get("cached_candidate_path")) or _cached_photo(update)
            if raw:
                await _accept_user_photo(update, context, raw)
            else:
                session["state"] = "await_user_photo"
                await update.effective_message.reply_text("Последнее фото не найдено. Пришлите новое селфи.")
            _stop()
        if data == "celeb:upload_user":
            session["state"] = "await_user_photo"
            await update.effective_message.reply_text(
                "📤 Пришлите новое селфи. После загрузки откроется новое меню выбора знаменитости.",
                reply_markup=base._kb([[("❌ Отмена", "celeb:cancel")]]),
            )
            _stop()

        await base._on_callback(update, context)
        _stop()
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Celebrity Selfie callback failed data=%s: %s", data, exc)
        _clear_legacy_flows(context)
        session = base._session(context)
        session["state"] = "choose_user_photo" if _cached_photo(update) else "await_user_photo"
        await update.effective_message.reply_text(
            "⚠️ Не удалось открыть этот шаг. Сессия восстановлена — выберите последнее фото или загрузите новое.",
            reply_markup=base._kb([
                [("✅ Использовать последнее фото", "celeb:use_cached")],
                [("📤 Загрузить новое селфи", "celeb:upload_user")],
                [("❌ Отмена", "celeb:cancel")],
            ]),
        )
        _stop()


async def _exclusive_image(update: Any, context: Any) -> None:
    if not base._active(context):
        return
    try:
        _clear_legacy_flows(context)
        session = base._session(context)
        state = str(session.get("state") or "")
        raw = await base._download_image_from_update(update)
        if not raw:
            await update.effective_message.reply_text("Нужен файл изображения JPG, PNG или WEBP.")
            _stop()
        if state == "await_custom_refs":
            await base._on_image(update, context)
            _stop()
        if state == "generating":
            await update.effective_message.reply_text("⏳ Генерация уже выполняется. Дождитесь результата.")
            _stop()
        # Prevent the legacy 'Фото получено. Что сделать?' menu from intercepting.
        await _accept_user_photo(update, context, raw)
        _stop()
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Celebrity Selfie image routing failed: %s", exc)
        await update.effective_message.reply_text(
            "⚠️ Фото не удалось принять в этом шаге. Пришлите JPG/PNG/WEBP ещё раз или отмените режим.",
            reply_markup=base._kb([[("❌ Отмена", "celeb:cancel")]]),
        )
        _stop()


async def _exclusive_text(update: Any, context: Any) -> None:
    text = str(getattr(update.effective_message, "text", "") or "").strip()
    active = base._active(context)
    direct = _direct_catalog_match(text) if "селфи" in base._norm(text) else None
    if not active and direct is None:
        return
    try:
        _clear_legacy_flows(context)
        if not active:
            session = base._session(context)
            cached = _cached_photo(update)
            if not cached:
                session["state"] = "await_user_photo"
                session["pending_celebrity_id"] = direct.get("id") if direct else ""
                await update.effective_message.reply_text(
                    f"Нашёл в базе: {direct.get('display_name')}. Сначала пришлите своё селфи."
                )
                _stop()
            await _accept_user_photo(update, context, cached)
            await base._prepare_library_refs(update, context, direct)
            _stop()

        session = base._session(context)
        state = str(session.get("state") or "")
        if state == "choose_celebrity":
            match = _direct_catalog_match(text)
            if match:
                await update.effective_message.reply_text(
                    f"⭐ Нашёл в библиотеке: {match.get('display_name')}. Подготавливаю точные референсы."
                )
                await base._prepare_library_refs(update, context, match)
            else:
                results = base.search_catalog(text, 8)
                if results:
                    await update.effective_message.reply_text(
                        "Нашёл несколько вариантов. Выберите нужного человека:",
                        reply_markup=base._search_results_kb(results),
                    )
                else:
                    await update.effective_message.reply_text(
                        "В библиотеке совпадений нет. Загрузите 1–4 фотографии нужного человека.",
                        reply_markup=base._kb([
                            [("📤 Загрузить фото знаменитости", "celeb:custom_refs")],
                            [("⬅️ К выбору", "celeb:menu")],
                        ]),
                    )
            _stop()

        if state == "choose_user_photo":
            await update.effective_message.reply_text(
                "Сначала выберите последнее фото кнопкой или загрузите новое селфи.",
                reply_markup=base._kb([
                    [("✅ Использовать последнее фото", "celeb:use_cached")],
                    [("📤 Загрузить новое селфи", "celeb:upload_user")],
                ]),
            )
            _stop()

        await base._on_text(update, context)
        await update.effective_message.reply_text(
            "Продолжите текущий шаг кнопками выше. Для поиска знаменитости нажмите «Найти по имени».",
            reply_markup=base._kb([
                [("🔎 Найти по имени", "celeb:search")],
                [("⭐ К выбору знаменитости", "celeb:menu")],
                [("❌ Отмена", "celeb:cancel")],
            ]),
        )
        _stop()
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Celebrity Selfie text routing failed: %s", exc)
        await update.effective_message.reply_text(
            "⚠️ Не удалось обработать этот шаг. Вернитесь к выбору знаменитости.",
            reply_markup=base._kb([[("⭐ Выбрать знаменитость", "celeb:menu")], [("❌ Отмена", "celeb:cancel")]]),
        )
        _stop()


async def _diag_flow(update: Any, context: Any) -> None:
    session = base._session(context, create=False)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie Flow / {VERSION}\n"
        f"active={'yes' if bool(session) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"exclusive_priority=-10000\n"
        f"legacy_keys_cleared={len(_LEGACY_FLOW_KEYS)}"
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
                CallbackQueryHandler(_safe_callback, pattern=r"^(?:act:fun:aiselfie|celeb:).*"),
                group=-10000,
            )
            app.add_handler(
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, _exclusive_image),
                group=-10000,
            )
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, _exclusive_text),
                group=-10000,
            )
            app.add_handler(CommandHandler("diag_celebrity_flow", _diag_flow), group=-10000)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_runtime_async() -> None:
    global _RUNTIME_STARTED
    if _RUNTIME_STARTED:
        return
    _RUNTIME_STARTED = True

    def worker() -> None:
        while True:
            mod = base._runtime_module()
            if mod is not None:
                with contextlib.suppress(Exception):
                    mod.CELEBRITY_SELFIE_FLOW_VERSION = VERSION
            time.sleep(5)

    threading.Thread(target=worker, name="celebrity-selfie-v123-runtime", daemon=True).start()


__all__ = ["VERSION", "install_builder_hook", "install_runtime_async"]
