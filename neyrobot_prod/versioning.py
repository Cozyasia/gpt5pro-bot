# -*- coding: utf-8 -*-
"""Canonical Telegram /version owner for Neyro-Bot releases.

The legacy monolith and historical runtime overlays may still expose their own
``PATCH_VERSION`` attributes. The public /version command is owned by the
package release and reports component versions separately.
"""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any

from . import VERSION

VERSION_HANDLER_GROUP = -100000
_VERSION_BUILDER_HOOKED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _deploy_revision() -> str:
    raw = (os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or "").strip()
    return raw[:7] if raw else "unknown"


def _active_selfie_runtime() -> tuple[str, str]:
    """Return the production-default selfie owner separately from package VERSION."""
    try:
        from neyrobot_prod import V263_PRODUCTION_ACCEPTED
        accepted = bool(V263_PRODUCTION_ACCEPTED)
    except Exception:
        accepted = False
    if accepted:
        return "v263", "production accepted"
    return "v262", "experimental / not production accepted"


async def command(update: Any, context: Any) -> None:
    """Return package release plus active production component versions."""
    from telegram.ext import ApplicationHandlerStop

    try:
        # /version is also an integrity reassertion. Always reinstall the current
        # V246 owner; checking the version must never roll image behavior backwards.
        with contextlib.suppress(Exception):
            from neyrobot_prod.selfie_v246_quality_hardlock import install
            install()

        message = getattr(update, "effective_message", None)
        if message is not None:
            runtime = _runtime_module()
            active_selfie, v263_status = _active_selfie_runtime()
            lines = [
                f"✅ Код/пакет: {VERSION}",
                f"✅ Production AI-селфи runtime: {active_selfie}",
                f"• V263: {v263_status}",
            ]
            if runtime is not None:
                lines.extend([
                    "Компоненты:",
                    f"• медицина: {getattr(runtime, 'MEDICAL_ENGINE_VERSION', '—')}",
                    f"• медицинская карта: {getattr(runtime, 'MEDICAL_CARD_VERSION', '—')}",
                    f"• покупка кредитов: {getattr(runtime, 'CREDIT_STORE_VERSION', '—')}",
                    f"• AI-селфи: {getattr(runtime, 'CELEBRITY_SELFIE_VERSION', getattr(runtime, 'AI_SELFIE_RUNTIME_VERSION', '—'))}",
                    f"• хранилище героев: {getattr(runtime, 'SELFIE_STORAGE_VERSION', '—')}",
                    f"• команды AI-селфи: {getattr(runtime, 'SELFIE_COMMANDS_VERSION', '—')}",
                    f"• маршрут AI-селфи: {getattr(runtime, 'CELEBRITY_SELFIE_ROUTE', '—')}",
                ])
                last_provider = str(getattr(runtime, "AI_SELFIE_LAST_FACESWAP_PROVIDER", "") or "").strip()
                if last_provider:
                    lines.append(f"• последний фактический transfer: {last_provider}")
            lines.append(f"Git revision: {_deploy_revision()}")
            lines.append("Render: main.py · Start Command: python -u main.py")
            await message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def install_builder_hook() -> bool:
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
