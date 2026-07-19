# -*- coding: utf-8 -*-
"""Celebrity Selfie v127: exact callback integration and redundant routing.

v126 implemented the correct library-first wizard, but it relied on a catch-all
handler in one very low PTB group.  The production application has many runtime
overlays and only the first matching handler in a group is evaluated.  A group
collision could therefore prevent v126 from ever seeing ``fun:aiselfie`` even
though its diagnostic command was installed.

v127 keeps the v126 wizard and v122 catalog/generation engine, but installs
narrow, exact handlers in two unique priority groups.  It also clears the real
legacy state keys used by main.py.  This makes the current production callback
``fun:aiselfie`` and the older ``act:fun:aiselfie``/``pedit:aiselfie`` values
enter the same wizard before any legacy route can run.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any

import celebrity_selfie_v126 as core

VERSION = "v127-celebrity-selfie-exact-integration-2026-07-19"
_PRIMARY_GROUP = -2_000_000_000
_BACKUP_GROUP = -1_900_000_000
_BUILDER_FLAG = "_celebrity_selfie_v127_builder"
_HANDLER_FLAG = "_celebrity_selfie_v127_handlers"
log = logging.getLogger("gpt-bot.celebrity-selfie-v127")

ENTRY_CALLBACKS = {
    "fun:aiselfie",
    "act:fun:aiselfie",
    "pedit:aiselfie",
    "fun:ai_selfie",
    "act:fun:ai_selfie",
    "photo:aiselfie",
    "cs127:start",
}

# These are the actual legacy keys used by main.py, in addition to the historic
# aliases already known by v126.  Leaving even one of them behind lets the
# generic photo handler reopen the old name-only Comet/Nano Banana flow.
EXTRA_LEGACY_KEYS = {
    "awaiting_ai_selfie_photo",
    "awaiting_ai_selfie_prompt",
    "ai_selfie_preset_prompt",
    "ai_selfie_last_prompt",
    "ai_selfie_last_photo",
    "ai_selfie_photo",
    "ai_selfie_scene",
    "ai_selfie_mode",
    "ai_selfie_waiting",
    "pending_ai_selfie",
}

# Rebrand the reused clean wizard and strengthen its cleanup vocabulary.
core.VERSION = VERSION
core._GROUP = _PRIMARY_GROUP
core.KNOWN_ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)
core.LEGACY_KEYS.update(EXTRA_LEGACY_KEYS)


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _data(context: Any) -> dict[str, Any]:
    value = getattr(context, "user_data", None)
    return value if isinstance(value, dict) else {}


def _clear_legacy(context: Any) -> None:
    with contextlib.suppress(Exception):
        core._clear_legacy_state(context)
    data = _data(context)
    for key in EXTRA_LEGACY_KEYS:
        data.pop(key, None)


def _active(context: Any) -> bool:
    with contextlib.suppress(Exception):
        return bool(core._active(context))
    return False


def _is_entry_data(data: str) -> bool:
    value = str(data or "").casefold()
    return (
        data in ENTRY_CALLBACKS
        or "aiselfie" in value
        or "ai_selfie" in value
        or "ai-selfie" in value
    )


def _is_owned_data(data: str) -> bool:
    return _is_entry_data(data) or str(data or "").startswith(("cs126:", "cs127:", "celeb:"))


async def _safe_restart(update: Any, context: Any, reason: str = "") -> None:
    """Recover inside the feature without leaking the global generic error."""
    if reason:
        log.error("Celebrity Selfie recovery: %s", reason)
    try:
        with contextlib.suppress(Exception):
            core._clear_all(context)
        session = core._new_session(context)
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text(
            "📸 Точное AI-селфи со знаменитостью\n\n"
            "Пришлите своё чёткое селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP. "
            "После загрузки откроется каталог знаменитостей.",
            reply_markup=core._photo_choice_kb(False),
        )
    except Exception:
        log.exception("Celebrity Selfie fallback itself failed")
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(
                "Не удалось открыть режим. Нажмите «AI-селфи со звездой» ещё раз."
            )


async def _callback(update: Any, context: Any) -> None:
    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(getattr(query, "data", "") or "")
    if not _is_owned_data(data):
        return

    with contextlib.suppress(Exception):
        await query.answer()
    _clear_legacy(context)

    try:
        if _is_entry_data(data) or data == "cs127:start":
            await core._open(update, context)
            _stop()

        # v126 owns cs126:* and delegates celeb:* directly to the audited v122
        # catalog/reference/generation primitives.
        await core._callback(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Exact Celebrity Selfie callback failed data=%s", data)
        await _safe_restart(update, context, repr(exc))
        _stop()
    _stop()


async def _image(update: Any, context: Any) -> None:
    if not _active(context):
        return
    _clear_legacy(context)
    try:
        await core._image(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Exact Celebrity Selfie image routing failed")
        await _safe_restart(update, context, repr(exc))
        _stop()
    _stop()


async def _text(update: Any, context: Any) -> None:
    if not _active(context):
        return
    _clear_legacy(context)
    try:
        await core._text(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if isinstance(exc, ApplicationHandlerStop):
            raise
        log.exception("Exact Celebrity Selfie text routing failed")
        await _safe_restart(update, context, repr(exc))
        _stop()
    _stop()


async def _diag(update: Any, context: Any) -> None:
    session = core._session(context, create=False)
    app = getattr(context, "application", None)
    handlers = getattr(app, "handlers", {}) if app is not None else {}

    def names(group: int) -> str:
        result = []
        for handler in handlers.get(group, []):
            callback = getattr(handler, "callback", None)
            result.append(getattr(callback, "__name__", handler.__class__.__name__))
        return ",".join(result) or "-"

    legacy_present = sorted(key for key in EXTRA_LEGACY_KEYS if key in _data(context))
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if _active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        f"primary_group={_PRIMARY_GROUP}\n"
        f"primary_handlers={names(_PRIMARY_GROUP)}\n"
        f"backup_group={_BACKUP_GROUP}\n"
        f"backup_handlers={names(_BACKUP_GROUP)}\n"
        "entry_callback=fun:aiselfie\n"
        "exact_pattern=yes\n"
        "telegram_photo=enabled\n"
        "catalog=100\n"
        f"legacy_keys_present={','.join(legacy_present) if legacy_present else 'none'}"
    )
    _stop()


async def _error_handler(update: object, context: Any) -> None:
    """Suppress main.py's generic «Упс» only for this isolated feature."""
    query = getattr(update, "callback_query", None)
    data = str(getattr(query, "data", "") or "") if query is not None else ""
    if not (_is_owned_data(data) or _active(context)):
        return
    log.exception("Celebrity Selfie unhandled error intercepted: %s", getattr(context, "error", None))
    try:
        effective_message = getattr(update, "effective_message", None)
        if effective_message is not None:
            await effective_message.reply_text(
                "Не удалось завершить текущий шаг. Откройте режим AI-селфи повторно.",
                reply_markup=core._kb([[('📸 Открыть AI-селфи', 'cs127:start')]]),
            )
    finally:
        with contextlib.suppress(Exception):
            core._clear_all(context)
        _stop()


def _install_handlers(app: Any) -> None:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    if getattr(app, _HANDLER_FLAG, False):
        return

    pattern = r"^(?:.*(?:aiselfie|ai_selfie|ai-selfie).*|cs126:.*|cs127:.*|celeb:.*)$"

    # Two separate groups are deliberate. PTB evaluates only the first matching
    # handler inside a group. If another project overlay occupies one group, the
    # second exact handler still receives the update before main.py group 0/1.
    for group in (_PRIMARY_GROUP, _BACKUP_GROUP):
        app.add_handler(CallbackQueryHandler(_callback, pattern=pattern), group=group)
        app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _image), group=group)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=group)

    app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_PRIMARY_GROUP)
    app.add_error_handler(_error_handler)
    setattr(app, _HANDLER_FLAG, True)


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        _install_handlers(app)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = ["VERSION", "install_builder_hook"]
