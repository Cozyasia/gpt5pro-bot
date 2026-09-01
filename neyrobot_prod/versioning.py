# -*- coding: utf-8 -*-
"""Canonical Telegram /version owner for Neyro-Bot releases."""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any

from . import PRODUCTION_SELFIE_RUNTIME, VERSION, V263_PRODUCTION_ACCEPTED, V264_PRODUCTION_ACCEPTED, V265_PRODUCTION_ACCEPTED

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
    active = str(PRODUCTION_SELFIE_RUNTIME or "").strip().lower() or "unknown"
    if active == "v265" and bool(V265_PRODUCTION_ACCEPTED):
        return "v265", "68-point dense identity · single-owner ROI-only production"
    if active == "v264" and bool(V264_PRODUCTION_ACCEPTED):
        return "v264", "68-point dense identity · retired"
    if active == "v263" and bool(V263_PRODUCTION_ACCEPTED):
        return "v263", "68-point dense identity · retired"
    return active, "configuration mismatch"


def _reassert_production_selfie_runtime() -> None:
    """Reassert only V265; /version cannot activate a historical runtime."""
    active, _ = _active_selfie_runtime()
    if active != "v265":
        raise RuntimeError(f"Unsupported production selfie runtime: {active}")
    from neyrobot_prod.selfie_v265_single_owner import install
    install()


async def command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    try:
        with contextlib.suppress(Exception):
            _reassert_production_selfie_runtime()

        message = getattr(update, "effective_message", None)
        if message is not None:
            runtime = _runtime_module()
            active_selfie, runtime_status = _active_selfie_runtime()
            lines = [
                f"✅ Код/пакет: {VERSION}",
                f"✅ Production AI-селфи runtime: {active_selfie}",
                f"• Геометрия: {runtime_status}",
                "• Резервный face-transfer: отсутствует; при ошибке V265 завершает операцию без отката",
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
