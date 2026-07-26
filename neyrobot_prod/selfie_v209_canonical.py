# -*- coding: utf-8 -*-
"""V209 canonical Celebrity Selfie binding.

This layer is installed after the legacy model-policy stack. It binds the V208
public flow directly to the final PTB Application, so legacy V201/V207 handlers
cannot keep serving the one-selfie, flat-character workflow.
"""
from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from typing import Any

VERSION = "v209-selfie-canonical-binding-2026-07-26"
_HANDLER_FLAG = "_selfie_v209_canonical_bound"
_BUILDER_HOOKED = False
_WORKER_STARTED = False
_SERVICE_COMMAND_RE = re.compile(
    r"^/(?P<command>version|selfie_admin|diag_selfie_storage)(?:@[A-Za-z0-9_]+)?(?:\s|$)",
    re.IGNORECASE,
)


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _looks_like_application(value: Any) -> bool:
    return (
        value is not None
        and callable(getattr(value, "add_handler", None))
        and isinstance(getattr(value, "handlers", None), dict)
        and getattr(value, "bot", None) is not None
    )


async def version_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    try:
        message = getattr(update, "effective_message", None)
        if message is None:
            return
        runtime = _runtime_module()
        lines = [f"✅ Код запущен: {VERSION}"]
        if runtime is not None:
            lines.extend([
                "Компоненты:",
                f"• медицина: {getattr(runtime, 'MEDICAL_ENGINE_VERSION', '—')}",
                f"• медицинская карта: {getattr(runtime, 'MEDICAL_CARD_VERSION', '—')}",
                f"• покупка кредитов: {getattr(runtime, 'CREDIT_STORE_VERSION', '—')}",
                f"• AI-селфи: {VERSION}",
                f"• хранилище героев: {VERSION}",
                f"• команды AI-селфи: {VERSION}",
            ])
        lines.append("Render: main.py · Start Command: python -u main.py")
        await message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


async def raw_service_router(update: Any, context: Any) -> None:
    message = getattr(update, "effective_message", None)
    text = str(getattr(message, "text", "") or "").strip()
    match = _SERVICE_COMMAND_RE.match(text)
    if not match:
        return
    from neyrobot_prod import selfie_v208_overlay as v208

    command = match.group("command").lower()
    if command == "version":
        await version_command(update, context)
    elif command == "selfie_admin":
        await v208._admin_command(update, context)
    else:
        await v208._diag_storage(update, context)


async def reject_non_photo_selfie(update: Any, context: Any) -> None:
    """Do not let legacy video handlers complete the old one-selfie flow."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    runtime = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return
    if not base._active(runtime, context, int(user.id)):
        return
    await message.reply_text(
        "⚠️ Для AI-селфи нужны именно две отдельные фотографии, не видео. "
        "Пришлите селфи 1/2 анфас, затем селфи 2/2 с лёгким поворотом головы."
    )
    raise ApplicationHandlerStop


def _disable_legacy_reclaimers() -> None:
    """Prevent already-started legacy workers from taking ownership back."""
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_runtime_v207 as runtime_v207
        runtime_v207.patch_runtime = lambda: True
        runtime_v207._publish_versions = lambda mod: None
    with contextlib.suppress(Exception):
        from neyrobot_prod import celebrity_selfie_v203 as legacy_v203
        legacy_v203.patch = lambda: True


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208

    _disable_legacy_reclaimers()
    v208.patch()
    v208.VERSION = VERSION
    generator_v204.VERSION = VERSION
    commands_v206.VERSION = VERSION
    runtime_v207.VERSION = VERSION
    storage_v205.VERSION = VERSION
    storage_v205.admin_command = v208._admin_command
    storage_v205.diagnostic = v208._diag_storage
    base.callback = v208._public_callback
    base.media_entry = v208._public_media
    base.text_entry = v208._public_text
    base._generate = v208._generate

    runtime = _runtime_module()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v209-comet-five-reference"
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
    return True


def bind_application(app: Any) -> bool:
    if not _looks_like_application(app):
        return False
    if getattr(app, _HANDLER_FLAG, False):
        return True

    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod.selfie_v208_nav_guard import clear_before_mode_callback

    # Lower group numbers execute first. These handlers own the complete V209 flow.
    app.add_handler(CommandHandler("version", version_command), group=-2050)
    app.add_handler(CommandHandler("selfie_admin", v208._admin_command), group=-2049)
    app.add_handler(CommandHandler("diag_selfie_storage", v208._diag_storage), group=-2049)
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(_SERVICE_COMMAND_RE), raw_service_router),
        group=-2048,
    )
    app.add_handler(
        CallbackQueryHandler(clear_before_mode_callback, pattern=r"^mode:(?:root|study|work|fun|medicine)$"),
        group=-2047,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, v208._mode_router), group=-2046)
    app.add_handler(CallbackQueryHandler(v208._admin_callback, pattern=r"^ss208:"), group=-2045)
    app.add_handler(
        CallbackQueryHandler(
            v208._public_callback,
            pattern=r"^(?:cs201:|act:fun:aiselfie(?:_upload|_last|_custom)?$|act:fun:as_preset_|fun:aiselfie$)",
        ),
        group=-2044,
    )
    video_filter = getattr(filters, "VIDEO", None)
    video_note_filter = getattr(filters, "VIDEO_NOTE", None)
    if video_filter is not None:
        combined_video_filter = video_filter
        if video_note_filter is not None:
            combined_video_filter = combined_video_filter | video_note_filter
        app.add_handler(MessageHandler(combined_video_filter, reject_non_photo_selfie), group=-2043)
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL, v208._public_media),
        group=-2042,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, v208._public_text), group=-2041)
    setattr(app, _HANDLER_FLAG, True)
    return True


def bind_runtime_applications() -> int:
    runtime = _runtime_module()
    if runtime is None:
        return 0
    bound = 0
    seen: set[int] = set()
    for value in vars(runtime).values():
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        with contextlib.suppress(Exception):
            if bind_application(value):
                bound += 1
    return bound


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder
    except Exception:
        return False
    class_flag = "_selfie_v209_builder"
    if getattr(ApplicationBuilder, class_flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        patch_runtime()
        bind_application(app)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, class_flag, True)
    _BUILDER_HOOKED = True
    return True


def install_async() -> None:
    global _WORKER_STARTED
    install_builder_hook()
    patch_runtime()
    bind_runtime_applications()
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        # Keep ownership until every legacy startup worker has finished.
        stable = 0
        for _ in range(18000):
            try:
                patch_runtime()
                bind_runtime_applications()
                runtime = _runtime_module()
                if runtime is not None and callable(getattr(runtime, "_try_pay_then_do", None)):
                    stable += 1
                    if stable >= 1800:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v209-canonical").start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION", "version_command", "raw_service_router", "reject_non_photo_selfie", "patch_runtime",
    "bind_application", "bind_runtime_applications", "install_builder_hook",
    "install_async", "install",
]
