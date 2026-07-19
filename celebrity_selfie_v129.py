# -*- coding: utf-8 -*-
"""Celebrity Selfie v129: writable reference library and end-to-end catalog flow.

v128 fixed the per-user session directory, but the v122 reference downloader has
its own independent ``CelebrityLibrary`` instance rooted at
``/data/celebrity_library``. When Render has no writable persistent disk at
/data, selecting any catalog person fails before generation. v129 verifies the
reference root with an actual write probe, falls back to /tmp, and patches the
live v122 library instance before any callback is handled.
"""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import celebrity_selfie_v128 as previous

core = previous.core
engine = previous.engine

VERSION = "v129-celebrity-selfie-writable-reference-library-2026-07-19"
_GROUP = -2_000_000_000
_BUILDER_FLAG = "_celebrity_selfie_v129_builder"
_HANDLER_FLAG = "_celebrity_selfie_v129_handlers"
_LIBRARY_ROOT_ENV = "CELEBRITY_LIBRARY_ROOT"
_LIBRARY_FALLBACK = Path("/tmp/celebrity_library")
log = logging.getLogger("gpt-bot.celebrity-selfie-v129")

ENTRY_CALLBACKS = set(previous.ENTRY_CALLBACKS) | {
    "cs129:start",
    "fun:aiselfie",
    "act:fun:aiselfie",
    "pedit:aiselfie",
}

# Keep one owner/version through the complete v126 -> v127 -> v128 reuse chain.
previous.VERSION = VERSION
previous.ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)
previous.previous.VERSION = VERSION
previous.previous.ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)
core.VERSION = VERSION
core._GROUP = _GROUP
core.KNOWN_ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)


def _probe_writable(path: Path) -> Path | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write_probe_{os.getpid()}_{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return path
    except Exception as exc:
        log.warning("Celebrity reference root is not writable: %s (%s)", path, exc)
        return None


def _select_library_root() -> Path:
    configured = (os.environ.get(_LIBRARY_ROOT_ENV) or "").strip()
    candidates: list[Path] = []
    for raw in (
        configured,
        "/data/celebrity_library",
        "/data/celebrity_refs",
        str(_LIBRARY_FALLBACK),
    ):
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        verified = _probe_writable(candidate)
        if verified is not None:
            os.environ[_LIBRARY_ROOT_ENV] = str(verified)
            return verified

    final = Path(tempfile.mkdtemp(prefix="celebrity_library_"))
    os.environ[_LIBRARY_ROOT_ENV] = str(final)
    return final


_LIBRARY_ROOT = _select_library_root()
engine.LIBRARY.root = _LIBRARY_ROOT

# Patch the live instance method so a deleted/unmounted directory self-heals
# before each first-time reference download.
_ORIGINAL_ENSURE_REFS = engine.LIBRARY.ensure_refs


def _ensure_refs_writable(*args: Any, **kwargs: Any):
    global _LIBRARY_ROOT
    verified = _probe_writable(Path(engine.LIBRARY.root))
    if verified is None:
        _LIBRARY_ROOT = _select_library_root()
        engine.LIBRARY.root = _LIBRARY_ROOT
    else:
        _LIBRARY_ROOT = verified
    return _ORIGINAL_ENSURE_REFS(*args, **kwargs)


engine.LIBRARY.ensure_refs = _ensure_refs_writable

# v122's status line always says that references are saved on a persistent disk.
# That is incorrect when Render falls back to /tmp. Wrap only this one primitive
# with per-update proxies; no global Telegram object is mutated, so concurrent
# users remain isolated.
_ORIGINAL_PREPARE_LIBRARY_REFS = engine._prepare_library_refs


class _MessageProxy:
    def __init__(self, target: Any):
        self._target = target

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    async def reply_text(self, text: str, *args: Any, **kwargs: Any):
        value = str(text)
        old = "Первое обращение может занять до минуты; затем файлы сохранятся на постоянном диске."
        if old in value:
            root = Path(engine.LIBRARY.root)
            if str(root).startswith("/tmp/") or root == Path("/tmp"):
                replacement = (
                    "Первое обращение может занять до минуты; повторные обращения будут быстрее "
                    "до следующего перезапуска сервиса."
                )
            else:
                replacement = (
                    "Первое обращение может занять до минуты; затем файлы сохранятся "
                    "в кэше библиотеки."
                )
            value = value.replace(old, replacement)
        return await self._target.reply_text(value, *args, **kwargs)


class _UpdateProxy:
    def __init__(self, target: Any):
        self._target = target
        self.effective_message = _MessageProxy(target.effective_message)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


async def _prepare_library_refs(update: Any, context: Any, entry: dict[str, Any]) -> None:
    message = getattr(update, "effective_message", None)
    wrapped = _UpdateProxy(update) if message is not None else update
    await _ORIGINAL_PREPARE_LIBRARY_REFS(wrapped, context, entry)


engine._prepare_library_refs = _prepare_library_refs


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
        or str(data or "").startswith(("cs126:", "cs127:", "cs128:", "cs129:", "celeb:"))
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
        f"session_root={previous._SESSION_ROOT}\n"
        f"session_root_writable={'yes' if previous._probe_writable(previous._SESSION_ROOT) else 'no'}\n"
        f"library_root={engine.LIBRARY.root}\n"
        f"library_root_writable={'yes' if _probe_writable(Path(engine.LIBRARY.root)) else 'no'}\n"
        "telegram_photo=enabled\n"
        "catalog=100\n"
        "reference_flow=enabled"
    )
    raise ApplicationHandlerStop


def _install_handlers(app: Any) -> None:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

    if getattr(app, _HANDLER_FLAG, False):
        return

    pattern = r"^(?:.*(?:aiselfie|ai_selfie|ai-selfie).*|cs126:.*|cs127:.*|cs128:.*|cs129:.*|celeb:.*)$"
    app.add_handler(CallbackQueryHandler(_callback, pattern=pattern), group=_GROUP)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _image), group=_GROUP)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=_GROUP)
    app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_GROUP)
    app.add_error_handler(previous.previous._error_handler)
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
