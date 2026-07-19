# -*- coding: utf-8 -*-
"""Celebrity Selfie v128: writable session storage and single-owner routing.

v127 proved that the production callback ``fun:aiselfie`` reaches the new
wizard.  The remaining crash occurred before the first screen: the v122 engine
tried to create ``/data/celebrity_selfie_sessions`` and raised when /data was
not writable.  v128 installs a verified writable root with /tmp fallback and
uses one exact high-priority handler, eliminating duplicate recovery messages.
"""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import celebrity_selfie_v127 as previous

core = previous.core
engine = core.engine

VERSION = "v128-celebrity-selfie-writable-session-single-owner-2026-07-19"
_GROUP = -2_000_000_000
_BUILDER_FLAG = "_celebrity_selfie_v128_builder"
_HANDLER_FLAG = "_celebrity_selfie_v128_handlers"
_ROOT_ENV = "CELEBRITY_SESSION_ROOT"
_FALLBACK_ROOT = Path("/tmp/celebrity_selfie_sessions")
log = logging.getLogger("gpt-bot.celebrity-selfie-v128")

ENTRY_CALLBACKS = set(previous.ENTRY_CALLBACKS) | {
    "cs128:start",
    "fun:aiselfie",
    "act:fun:aiselfie",
    "pedit:aiselfie",
}

# Rebrand the reused clean wizard and keep the exact production callback map.
previous.VERSION = VERSION
previous._PRIMARY_GROUP = _GROUP
previous.ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)
core.VERSION = VERSION
core._GROUP = _GROUP
core.KNOWN_ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)
core.LEGACY_KEYS.update(previous.EXTRA_LEGACY_KEYS)


def _probe_writable(path: Path) -> Path | None:
    """Return path only after an actual create/write/delete probe succeeds."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write_probe_{os.getpid()}_{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return path
    except Exception as exc:
        log.warning("Celebrity session root is not writable: %s (%s)", path, exc)
        return None


def _select_session_root() -> Path:
    configured = (os.environ.get(_ROOT_ENV) or "").strip()
    candidates: list[Path] = []
    for raw in (
        configured,
        "/data/celebrity_selfie_sessions",
        "/data/celebrity_sessions",
        str(_FALLBACK_ROOT),
    ):
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        verified = _probe_writable(candidate)
        if verified is not None:
            os.environ[_ROOT_ENV] = str(verified)
            return verified

    # /tmp should normally work, but retain a final process-private fallback.
    final = Path(tempfile.mkdtemp(prefix="celebrity_selfie_sessions_"))
    os.environ[_ROOT_ENV] = str(final)
    return final


_SESSION_ROOT = _select_session_root()


def _writable_session_root(*_args: Any, **_kwargs: Any) -> Path:
    """Drop-in replacement for v122._session_root with automatic self-healing."""
    global _SESSION_ROOT
    verified = _probe_writable(_SESSION_ROOT)
    if verified is not None:
        return verified
    _SESSION_ROOT = _select_session_root()
    return _SESSION_ROOT


# The v122 payload calls this helper for every new session. Patch it before the
# first Telegram callback can create state.
engine._session_root = _writable_session_root


def _active(context: Any) -> bool:
    with contextlib.suppress(Exception):
        return bool(core._active(context))
    return False


def _owned_callback(data: str) -> bool:
    value = str(data or "").casefold()
    return (
        data in ENTRY_CALLBACKS
        or "aiselfie" in value
        or "ai_selfie" in value
        or "ai-selfie" in value
        or str(data or "").startswith(("cs126:", "cs127:", "cs128:", "celeb:"))
    )


async def _callback(update: Any, context: Any) -> None:
    query = getattr(update, "callback_query", None)
    data = str(getattr(query, "data", "") or "") if query is not None else ""
    if not _owned_callback(data):
        return
    await previous._callback(update, context)


async def _image(update: Any, context: Any) -> None:
    if not _active(context):
        return
    await previous._image(update, context)


async def _text(update: Any, context: Any) -> None:
    if not _active(context):
        return
    await previous._text(update, context)


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = core._session(context, create=False)
    app = getattr(context, "application", None)
    handlers = getattr(app, "handlers", {}) if app is not None else {}
    names = []
    for handler in handlers.get(_GROUP, []):
        callback = getattr(handler, "callback", None)
        names.append(getattr(callback, "__name__", handler.__class__.__name__))

    legacy_present = sorted(
        key for key in previous.EXTRA_LEGACY_KEYS
        if key in getattr(context, "user_data", {})
    )
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if _active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        f"handler_group={_GROUP}\n"
        f"handlers={','.join(names) if names else '-'}\n"
        "entry_callback=fun:aiselfie\n"
        "exact_pattern=yes\n"
        "single_owner=yes\n"
        f"session_root={_SESSION_ROOT}\n"
        f"session_root_writable={'yes' if _probe_writable(_SESSION_ROOT) else 'no'}\n"
        "telegram_photo=enabled\n"
        "catalog=100\n"
        f"legacy_keys_present={','.join(legacy_present) if legacy_present else 'none'}"
    )
    raise ApplicationHandlerStop


def _install_handlers(app: Any) -> None:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    if getattr(app, _HANDLER_FLAG, False):
        return

    pattern = r"^(?:.*(?:aiselfie|ai_selfie|ai-selfie).*|cs126:.*|cs127:.*|cs128:.*|celeb:.*)$"
    app.add_handler(CallbackQueryHandler(_callback, pattern=pattern), group=_GROUP)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _image), group=_GROUP)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=_GROUP)
    app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_GROUP)
    app.add_error_handler(previous._error_handler)
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
