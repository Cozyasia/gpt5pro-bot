# -*- coding: utf-8 -*-
"""V206: deterministic routing for Celebrity Selfie service commands.

V205 storage and character catalogue are kept intact. This layer only makes
/version, /selfie_admin and /diag_selfie_storage deterministic by registering
them before every legacy router and by binding them to an already-created PTB
Application as a fallback.
"""
from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from typing import Any

VERSION = "v206-selfie-command-routing-2026-07-25"
VERSION_HANDLER_GROUP = -1700
COMMAND_HANDLER_GROUP = -1600
RAW_COMMAND_GROUP = -1599
MEDIA_HANDLER_GROUP = -1598

_BUILDER_HOOKED = False
_WORKER_STARTED = False
_COMMAND_RE = re.compile(
    r"^/(?P<command>selfie_admin|diag_selfie_storage)(?:@[A-Za-z0-9_]+)?(?:\s|$)",
    re.IGNORECASE,
)


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _install_authorization_owner() -> None:
    """Use the complete V202 owner/admin policy inside the V205 catalogue."""
    from neyrobot_prod import selfie_admin_v202 as admin_v202
    from neyrobot_prod import selfie_storage_v205 as storage_v205

    storage_v205._authorized = lambda runtime, user: admin_v202.is_admin(runtime, user)


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
                f"• AI-селфи: {getattr(runtime, 'CELEBRITY_SELFIE_VERSION', getattr(runtime, 'AI_SELFIE_RUNTIME_VERSION', '—'))}",
                f"• хранилище героев: {getattr(runtime, 'SELFIE_STORAGE_VERSION', '—')}",
                f"• команды AI-селфи: {VERSION}",
            ])
        lines.append("Render: main.py · Start Command: python -u main.py")
        await message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


async def raw_command_router(update: Any, context: Any) -> None:
    """Fallback when a client sends command-like text without command entities."""
    message = getattr(update, "effective_message", None)
    text = str(getattr(message, "text", "") or "").strip()
    match = _COMMAND_RE.match(text)
    if not match:
        return

    from neyrobot_prod import selfie_storage_v205 as storage_v205

    command = match.group("command").lower()
    if command == "selfie_admin":
        await storage_v205.admin_command(update, context)
    else:
        await storage_v205.diagnostic(update, context)


def bind_application(app: Any) -> bool:
    """Attach the final service routes directly to one PTB Application."""
    if not _looks_like_application(app):
        return False

    flag = "_selfie_commands_v206_bound"
    if getattr(app, flag, False):
        return True

    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    from neyrobot_prod import selfie_storage_v205 as storage_v205

    _install_authorization_owner()
    app.add_handler(CommandHandler("version", version_command), group=VERSION_HANDLER_GROUP)
    app.add_handler(CommandHandler("selfie_admin", storage_v205.admin_command), group=COMMAND_HANDLER_GROUP)
    app.add_handler(CommandHandler("diag_selfie_storage", storage_v205.diagnostic), group=COMMAND_HANDLER_GROUP)
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(_COMMAND_RE), raw_command_router),
        group=RAW_COMMAND_GROUP,
    )
    app.add_handler(
        CallbackQueryHandler(storage_v205.callback, pattern=r"^ss205:"),
        group=COMMAND_HANDLER_GROUP,
    )
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL, storage_v205.media_entry),
        group=MEDIA_HANDLER_GROUP,
    )
    setattr(app, flag, True)
    return True


def bind_runtime_applications() -> int:
    """Bind routes even when this layer was imported after Application.build()."""
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
    """Install before main.py builds the Telegram application."""
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True

    try:
        from telegram.ext import ApplicationBuilder
    except Exception:
        return False

    class_flag = "_selfie_commands_v206_builder"
    if getattr(ApplicationBuilder, class_flag, False):
        _BUILDER_HOOKED = True
        return True

    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        bind_application(app)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, class_flag, True)
    _BUILDER_HOOKED = True
    return True


def patch_runtime() -> bool:
    _install_authorization_owner()
    runtime = _runtime_module()
    if runtime is not None:
        runtime.SELFIE_COMMANDS_VERSION = VERSION
    bind_runtime_applications()
    return True


def install_async() -> None:
    global _WORKER_STARTED
    install_builder_hook()
    _install_authorization_owner()
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(2400):
            try:
                patch_runtime()
                runtime = _runtime_module()
                if runtime is not None and callable(getattr(runtime, "_try_pay_then_do", None)):
                    stable += 1
                    if stable >= 300:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(
        target=worker,
        daemon=True,
        name="neyrobot-selfie-commands-v206",
    ).start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "VERSION_HANDLER_GROUP",
    "COMMAND_HANDLER_GROUP",
    "RAW_COMMAND_GROUP",
    "MEDIA_HANDLER_GROUP",
    "version_command",
    "raw_command_router",
    "bind_application",
    "bind_runtime_applications",
    "install_builder_hook",
    "patch_runtime",
    "install_async",
    "install",
]
