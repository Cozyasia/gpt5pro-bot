# -*- coding: utf-8 -*-
"""Persistent Medicine-mode media routing for Neyro-Bot v116.

Once the user opens the top-level Medicine mode, photos are treated as medical
materials until the user presses Back, opens the main menu, or selects another
mode. The patch is intentionally modular: it installs high-priority PTB handlers
before the legacy generic-photo router and reuses the current medical engine.
"""
from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from typing import Any

VERSION = "v116-medical-sticky-mode-2026-07-18"
_PATCH_FLAG = "_MEDICAL_MODE_V116_PATCHED"
_BUILDER_FLAG = "_MEDICAL_MODE_V116_BUILDER_HOOKED"
_ACTIVE_USERS: set[int] = set()
_ACTIVE_LOCK = threading.RLock()

_EXIT_TEXTS = {
    "назад",
    "главное меню",
    "меню",
    "меню ботов",
    "учеба",
    "работа",
    "работа бизнес",
    "бизнес",
    "развлечения",
    "актуальная информация",
    "мои чаты",
    "баланс и подписка",
    "движки",
    "о боте",
}

_CONFLICTING_FLAGS = (
    "awaiting_photo_for",
    "photo_flow",
    "awaiting_avatar_photo",
    "awaiting_ai_selfie_photo",
    "awaiting_vocal_clip_photo",
    "awaiting_photo_clip_photo",
    "retouch_wait_text",
    "awaiting_reels_material",
    "awaiting_film_material",
)


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _normalize_label(value: str) -> str:
    value = (value or "").lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _is_medicine_label(value: str) -> bool:
    return _normalize_label(value) in {"медицина", "medicine", "medical"}


def _is_exit_label(value: str) -> bool:
    return _normalize_label(value) in _EXIT_TEXTS


def _callback_is_medical(data: str) -> bool:
    d = (data or "").strip().lower()
    if not d:
        return False
    return (
        d.startswith("med:")
        or d.startswith("med_")
        or d.startswith("medcard:")
        or d.startswith("medical:")
        or d.startswith("medicine:")
        or d in {"med", "medical", "medicine", "mode:med", "mode:medical", "mode:medicine"}
        or (d.startswith("mode:") and any(token in d for token in ("med", "medicine", "medical")))
    )


def _callback_leaves_medical(data: str) -> bool:
    d = (data or "").strip().lower()
    if not d or _callback_is_medical(d):
        return False
    if d in {"back", "main", "menu", "home", "start"}:
        return True
    if d.startswith(("back:", "main:", "menu:", "home:", "mode:", "study:", "work:", "fun:", "engine:")):
        return True
    return True


def _remember_active(user_id: int) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_USERS.add(int(user_id))


def _forget_active(user_id: int) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_USERS.discard(int(user_id))


def _memory_active(user_id: int) -> bool:
    with _ACTIVE_LOCK:
        return int(user_id) in _ACTIVE_USERS


def _activate(mod: Any, context: Any, user_id: int) -> None:
    uid = int(user_id)
    _remember_active(uid)
    if context is not None:
        context.user_data["medical_mode_active"] = True
        context.user_data["medical_mode_entered_ts"] = int(time.time())
        for key in _CONFLICTING_FLAGS:
            context.user_data.pop(key, None)
    setter = getattr(mod, "_mode_set", None)
    if callable(setter):
        with contextlib.suppress(Exception):
            setter(uid, "Медицина")


def _deactivate(mod: Any, context: Any, user_id: int) -> None:
    uid = int(user_id)
    _forget_active(uid)
    if context is not None:
        context.user_data.pop("medical_mode_active", None)
        context.user_data.pop("medical_mode_entered_ts", None)


def _is_active(mod: Any, context: Any, user_id: int) -> bool:
    uid = int(user_id)
    if context is not None and bool(context.user_data.get("medical_mode_active")):
        _remember_active(uid)
        return True
    if _memory_active(uid):
        return True

    mode = ""
    track = ""
    getter = getattr(mod, "_mode_get", None)
    if callable(getter):
        with contextlib.suppress(Exception):
            mode = str(getter(uid) or "")
    track_getter = getattr(mod, "_mode_track_get", None)
    if callable(track_getter):
        with contextlib.suppress(Exception):
            track = str(track_getter(uid) or "")
    active = _is_medicine_label(mode) or track.lower().startswith("med_")
    if active:
        _activate(mod, context, uid)
    return active


async def _entry_text_mode(update: Any, context: Any) -> None:
    mod = _runtime_module()
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    text = str(getattr(message, "text", "") or "")
    if mod is None or user is None:
        return
    if _is_medicine_label(text):
        _activate(mod, context, user.id)
    elif _is_exit_label(text):
        _deactivate(mod, context, user.id)


async def _entry_callback_mode(update: Any, context: Any) -> None:
    mod = _runtime_module()
    query = getattr(update, "callback_query", None)
    user = getattr(update, "effective_user", None)
    if mod is None or query is None or user is None:
        return
    data = str(getattr(query, "data", "") or "")
    if _callback_is_medical(data):
        _activate(mod, context, user.id)
    elif _is_active(mod, context, user.id) and _callback_leaves_medical(data):
        _deactivate(mod, context, user.id)


async def _entry_exit_command(update: Any, context: Any) -> None:
    mod = _runtime_module()
    user = getattr(update, "effective_user", None)
    if mod is not None and user is not None:
        _deactivate(mod, context, user.id)


async def _entry_photo(update: Any, context: Any) -> None:
    mod = _runtime_module()
    message = getattr(update, "message", None)
    user = getattr(update, "effective_user", None)
    if mod is None or message is None or user is None or not getattr(message, "photo", None):
        return
    if not _is_active(mod, context, user.id):
        return

    update_id = int(getattr(update, "update_id", 0) or 0)
    if update_id and context.user_data.get("medical_mode_last_update_id") == update_id:
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop
    if update_id:
        context.user_data["medical_mode_last_update_id"] = update_id

    try:
        photo = message.photo[-1]
        tg_file = await photo.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        if not raw:
            raise ValueError("empty photo")
        file_token = str(getattr(photo, "file_unique_id", "") or update_id or int(time.time()))
        context.user_data["medcard_source_capture"] = {
            "file_bytes": raw,
            "filename": f"medical_photo_{file_token}.jpg",
            "mime_type": "image/jpeg",
        }
        goal = str(getattr(message, "caption", "") or "").strip() or None
        analyzer = getattr(mod, "_medical_analyze_image", None)
        if not callable(analyzer):
            raise RuntimeError("medical analyzer unavailable")
        await analyzer(update, context, raw, goal)
    except Exception as exc:
        logger = getattr(mod, "log", None)
        if logger is not None:
            with contextlib.suppress(Exception):
                logger.exception("medical sticky photo routing failed: %r", exc)
        keyboard = None
        with contextlib.suppress(Exception):
            keyboard = mod.medicine_kb()
        await message.reply_text(
            "⚠️ Не удалось передать фотографию в медицинский анализ. Повторите загрузку; "
            "режим «Медицина» остаётся активным.",
            reply_markup=keyboard,
        )
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def install_builder_hook() -> None:
    try:
        from telegram.ext import (
            ApplicationBuilder,
            CallbackQueryHandler,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return

    original_build = ApplicationBuilder.build

    def build(self, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _BUILDER_FLAG, False):
            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, _entry_text_mode),
                group=-20,
            )
            app.add_handler(CallbackQueryHandler(_entry_callback_mode), group=-20)
            app.add_handler(CommandHandler("start", _entry_exit_command), group=-20)
            app.add_handler(CommandHandler("menu", _entry_exit_command), group=-20)
            app.add_handler(MessageHandler(filters.PHOTO, _entry_photo), group=-19)
            setattr(app, _BUILDER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def _install_source_fidelity_guards() -> None:
    with contextlib.suppress(Exception):
        import medical_v114_overlay as overlay

        extra_reason = """

ADDITIONAL SOURCE-FIDELITY RULES
• Never transfer a descriptor from one anatomical layer or organ to another. In gynecologic ultrasound, keep myometrium, endometrium/M-echo, cervix, ovaries and adnexal findings separate.
• If the source states that M-echo/endometrial contours are smooth/clear and structure is homogeneous, do not call the endometrium irregular. M-echo thickness alone must not be presented as proof of adenomyosis; adenomyosis assessment depends on myometrial signs, symptoms and the complete examination.
• Do not invent a short follow-up interval for a tiny uncomplicated incidental cyst or lesion. State that timing depends on symptoms, morphology, prior dynamics and the treating clinician unless the source or cited guideline supplies a specific interval.
• Recommend only tests that can change management and explain their purpose. Avoid broad laboratory panels by default.
• Before finalizing, verify that every adjective (smooth/irregular, homogeneous/heterogeneous, vascular/avascular) remains attached to the exact structure described in the source.
"""
        if "ADDITIONAL SOURCE-FIDELITY RULES" not in overlay.REASON_SYSTEM:
            overlay.REASON_SYSTEM += extra_reason

        extra_audit = """

ADDITIONAL AUDIT CHECKS
• Reject the answer if any contour, echogenicity, homogeneity, vascularity, side or measurement was moved to another structure.
• Specifically verify that M-echo/endometrium is not confused with myometrium and that M-echo thickness is not used alone to establish adenomyosis.
• Remove arbitrary short surveillance intervals and unnecessary broad laboratory testing not supported by the source or guideline context.
"""
        if "ADDITIONAL AUDIT CHECKS" not in overlay.AUDIT_SYSTEM:
            overlay.AUDIT_SYSTEM += extra_audit


def patch_runtime(mod: Any) -> bool:
    if getattr(mod, _PATCH_FLAG, False):
        mod.PATCH_VERSION = VERSION
        mod.MEDICAL_MODE_VERSION = VERSION
        return True

    analyzer = getattr(mod, "_medical_analyze_image", None)
    router = getattr(mod, "_should_route_medical", None)
    if not callable(analyzer) or not callable(router):
        return False

    original_router = router
    if not getattr(original_router, "_medical_v116_wrapped", False):
        def should_route(context: Any, user_id: int, caption_or_text: str = "", filename: str = "") -> bool:
            if _is_active(mod, context, int(user_id)):
                return True
            return bool(original_router(context, user_id, caption_or_text, filename))

        should_route._medical_v116_wrapped = True
        mod._should_route_medical = should_route

    original_track_get = getattr(mod, "_mode_track_get", None)
    if callable(original_track_get) and not getattr(original_track_get, "_medical_v116_wrapped", False):
        def track_get(user_id: int):
            value = original_track_get(user_id)
            if _memory_active(int(user_id)) and not str(value or "").lower().startswith("med_"):
                return "med_scan"
            return value

        track_get._medical_v116_wrapped = True
        mod._mode_track_get = track_get

    original_menu_text = getattr(mod, "_medical_menu_text", None)
    if callable(original_menu_text) and not getattr(original_menu_text, "_medical_v116_wrapped", False):
        def menu_text(track: str = "") -> str:
            text = str(original_menu_text(track) or "").rstrip()
            notice = (
                "\n\n✅ Режим «Медицина» остаётся активным: следующая фотография или документ "
                "автоматически будут направлены на медицинский анализ. Для выхода нажмите «Назад» "
                "или выберите другой режим."
            )
            return text if "остаётся активным" in text else text + notice

        menu_text._medical_v116_wrapped = True
        mod._medical_menu_text = menu_text

    _install_source_fidelity_guards()
    mod.MEDICAL_MODE_VERSION = VERSION
    mod.MEDICAL_PATCH_VERSION = VERSION
    mod.MEDICAL_CARD_VERSION = VERSION
    mod.PATCH_VERSION = VERSION
    setattr(mod, _PATCH_FLAG, True)
    return True


def install_async() -> None:
    def worker() -> None:
        patched_mod = None
        for _ in range(12000):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is None:
                    continue
                with contextlib.suppress(Exception):
                    if patch_runtime(mod):
                        patched_mod = mod
                        break
            if patched_mod is not None:
                break
            time.sleep(0.02)

        if patched_mod is not None:
            for _ in range(1200):
                with contextlib.suppress(Exception):
                    patched_mod.PATCH_VERSION = VERSION
                    patched_mod.MEDICAL_MODE_VERSION = VERSION
                    patched_mod.MEDICAL_PATCH_VERSION = VERSION
                    patched_mod.MEDICAL_CARD_VERSION = VERSION
                time.sleep(0.2)

    threading.Thread(target=worker, daemon=True, name="medical-mode-v116").start()


__all__ = ["VERSION", "install_builder_hook", "patch_runtime", "install_async"]
