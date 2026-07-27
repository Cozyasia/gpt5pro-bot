# -*- coding: utf-8 -*-
"""V220: make V219 the visible and executable canonical selfie runtime.

V219 owned callbacks/media, but V218's earlier /version and diagnostic command
handlers retained hard-coded V218 callback objects. This layer binds command
handlers at a still earlier PTB group and synchronizes every public version field.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v220-selfie-triref-scene-canonical-2026-07-27"
_HANDLER_FLAG = "_selfie_v220_runtime_marker_bound"
_BUILDER_FLAG = "_selfie_v220_builder_hooked"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator
    from neyrobot_prod import selfie_commands_v206 as commands
    from neyrobot_prod import selfie_runtime_v207 as legacy
    from neyrobot_prod import selfie_storage_v205 as storage
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    v219.patch_runtime()
    for module in (base, generator, commands, legacy, storage, v208, v209, v215, v217, v218, v219):
        with contextlib.suppress(Exception):
            module.VERSION = VERSION

    mod = _runtime()
    if mod is not None:
        mod.CELEBRITY_SELFIE_VERSION = VERSION
        mod.AI_SELFIE_RUNTIME_VERSION = VERSION
        mod.SELFIE_STORAGE_VERSION = VERSION
        mod.SELFIE_COMMANDS_VERSION = VERSION
        mod.SELFIE_ADMIN_VERSION = VERSION
        mod.CELEBRITY_SELFIE_ROUTE = "v220-v219-canonical-3-user-3-hero-optional-scene"
        mod.AI_SELFIE_USER_REFERENCES = 3
        mod.AI_SELFIE_HERO_REFERENCES = 3
    return True


async def version_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    try:
        patch_runtime()
        msg = getattr(update, "effective_message", None)
        if msg is None:
            return
        mod = _runtime()
        lines = [f"✅ Код запущен: {VERSION}"]
        if mod is not None:
            lines.extend([
                "Компоненты:",
                f"• медицина: {getattr(mod, 'MEDICAL_ENGINE_VERSION', '—')}",
                f"• медицинская карта: {getattr(mod, 'MEDICAL_CARD_VERSION', '—')}",
                f"• покупка кредитов: {getattr(mod, 'CREDIT_STORE_VERSION', '—')}",
                f"• AI-селфи: {VERSION}",
                f"• хранилище героев: {VERSION}",
                f"• команды AI-селфи: {VERSION}",
                "• фото пользователя: 3",
                "• фото героя: 3",
                "• фото сцены: отдельный референс 0/1",
            ])
        lines.append("Render: main.py · Start Command: python -u main.py")
        await msg.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_v217_user_triref as v217
    try:
        patch_runtime()
        await v217.diagnostic(update, context)
    finally:
        raise ApplicationHandlerStop


def _is_app(value: Any) -> bool:
    return value is not None and callable(getattr(value, "add_handler", None)) and isinstance(getattr(value, "handlers", None), dict)


def bind_application(app: Any) -> bool:
    if not _is_app(app):
        return False
    if getattr(app, _HANDLER_FLAG, False):
        return True
    from telegram.ext import CommandHandler
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    v219.bind_application(app)
    app.add_handler(CommandHandler("version", version_command), group=-6002)
    app.add_handler(CommandHandler("diag_selfie_storage", diagnostic), group=-6001)
    setattr(app, _HANDLER_FLAG, True)
    return True


def bind_runtime_apps() -> int:
    mod = _runtime()
    if mod is None:
        return 0
    count = 0
    seen: set[int] = set()
    for value in vars(mod).values():
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        with contextlib.suppress(Exception):
            if bind_application(value):
                count += 1
    return count


def install_builder_hook() -> bool:
    try:
        from telegram.ext import ApplicationBuilder
    except Exception:
        return False
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return True
    original = ApplicationBuilder.build
    def build(self: Any, *args: Any, **kwargs: Any):
        app = original(self, *args, **kwargs)
        patch_runtime()
        bind_application(app)
        return app
    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)
    return True


def install_async() -> None:
    global _STARTED
    install_builder_hook()
    patch_runtime()
    bind_runtime_apps()
    if _STARTED:
        return
    _STARTED = True
    def worker() -> None:
        for _ in range(21600):
            with contextlib.suppress(Exception):
                patch_runtime()
                bind_runtime_apps()
            time.sleep(0.1)
    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v220-marker").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "version_command", "diagnostic", "patch_runtime", "bind_application", "install_async", "install"]
