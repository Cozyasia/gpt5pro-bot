# -*- coding: utf-8 -*-
"""Canonical Telegram /version owner for Neyro-Bot releases.

The legacy monolith and historical runtime overlays may still expose their own
``PATCH_VERSION`` attributes. The public /version command is owned by the
package release and reports component versions separately.
"""
from __future__ import annotations

import sys
from typing import Any

from . import VERSION

VERSION_HANDLER_GROUP = -1000
_VERSION_BUILDER_HOOKED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


async def command(update: Any, context: Any) -> None:
    """Return the package release plus the active production component versions."""
    from telegram.ext import ApplicationHandlerStop

    try:
        message = getattr(update, "effective_message", None)
        if message is not None:
            runtime = _runtime_module()
            lines = [f"✅ Код запущен: {VERSION}"]
            if runtime is not None:
                lines.extend([
                    "Компоненты:",
                    f"• медицина: {getattr(runtime, 'MEDICAL_ENGINE_VERSION', '—')}",
                    f"• медицинская карта: {getattr(runtime, 'MEDICAL_CARD_VERSION', '—')}",
                    f"• покупка кредитов: {getattr(runtime, 'CREDIT_STORE_VERSION', '—')}",
                    f"• AI-селфи: {getattr(runtime, 'CELEBRITY_SELFIE_VERSION', getattr(runtime, 'AI_SELFIE_RUNTIME_VERSION', '—'))}",
                    f"• сервисное меню селфи: {getattr(runtime, 'SELFIE_ADMIN_VERSION', '—')}",
                ])
            lines.append("Render: main.py · Start Command: python -u main.py")
            await message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def install_builder_hook() -> bool:
    """Install exactly one highest-priority /version handler."""
    global _VERSION_BUILDER_HOOKED
    if _VERSION_BUILDER_HOOKED:
        return True

    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return False

    class_flag = "_neyrobot_canonical_version_hooked"
    app_flag = "_neyrobot_canonical_version_handler"
    if getattr(ApplicationBuilder, class_flag, False):
        _VERSION_BUILDER_HOOKED = True
        return True

    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, app_flag, False):
            app.add_handler(CommandHandler("version", command), group=VERSION_HANDLER_GROUP)
            setattr(app, app_flag, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, class_flag, True)
    _VERSION_BUILDER_HOOKED = True
    return True


__all__ = ["VERSION", "VERSION_HANDLER_GROUP", "command", "install_builder_hook"]
