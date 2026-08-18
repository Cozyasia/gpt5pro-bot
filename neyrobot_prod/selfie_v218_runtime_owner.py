# -*- coding: utf-8 -*-
"""V235 compatibility bridge: keep legacy selfie UI, never restore legacy generation.

The historical V218 owner used to call V219.patch_runtime() every 100 ms. That
continuously restored V219's Comet/Gemini-only generate function and could overwrite
the newer V234 real-FaceSwap owner after deployment. This bridge keeps the proven
V219 three-photo UI and retained PTB handlers, but makes V234 the only generation
implementation and permanently neutralizes V219's legacy repair loop.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v235-v234-authoritative-faceswap-compat-2026-08-18"
_HANDLER_FLAG = "_selfie_v218_runtime_owner_bound"
_BUILDER_FLAG = "_selfie_v218_builder_hooked"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _is_app(value: Any) -> bool:
    return value is not None and callable(getattr(value, "add_handler", None)) and isinstance(getattr(value, "handlers", None), dict)


def _legacy_noop(*args: Any, **kwargs: Any) -> bool:
    return True


def patch_runtime() -> bool:
    """Route every retained selfie alias to V234 without invoking V219.patch_runtime."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator
    from neyrobot_prod import selfie_commands_v206 as commands
    from neyrobot_prod import selfie_runtime_v207 as legacy_runtime
    from neyrobot_prod import selfie_storage_v205 as storage
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v233_true_face_transfer as v234

    # Critical fix: stop the historical V219 repair worker from ever restoring
    # Comet generation. A worker already running resolves this global function on
    # every iteration, so replacing the module attributes also neutralizes it live.
    v219.patch_runtime = _legacy_noop
    v219.bind_runtime_apps = lambda *args, **kwargs: 0
    v219.install_builder_hook = _legacy_noop
    v219.install_async = lambda *args, **kwargs: None
    v219.install = lambda *args, **kwargs: None

    # Keep V219 UI/media callbacks, but force the function they call for generation
    # to be the real V234 FaceSwap pipeline.
    v219.generate = v234.generate
    with contextlib.suppress(Exception):
        v219.public_callback.__globals__["generate"] = v234.generate

    base.callback = v219.public_callback
    base.media_entry = v219.public_media
    base._generate = v234.generate
    v208._public_callback = v219.public_callback
    v208._public_media = v219.public_media
    v208._public_text = v219.public_text
    v208._generate = v234.generate
    v208._diag_storage = v217.diagnostic
    storage.diagnostic = v217.diagnostic

    # Older modules may be queried for VERSION, but none may own generation.
    for module in (v217, v208, v209, generator, commands, legacy_runtime, storage):
        with contextlib.suppress(Exception):
            module.VERSION = VERSION

    mod = _runtime()
    if mod is not None:
        mod.CELEBRITY_SELFIE_VERSION = VERSION
        mod.AI_SELFIE_RUNTIME_VERSION = VERSION
        mod.SELFIE_STORAGE_VERSION = VERSION
        mod.SELFIE_COMMANDS_VERSION = VERSION
        mod.CELEBRITY_SELFIE_ROUTE = "v235-v219-ui-v234-real-faceswap"
        mod.AI_SELFIE_PROVIDER = "Gemini composition + real FaceSwap"
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
        await msg.reply_text(
            "\n".join([
                f"✅ Код запущен: {VERSION}",
                "• AI-селфи UI: V219 (3 фото пользователя + 3 фото героя)",
                "• генерация сцены: Gemini",
                "• лицо пользователя: V234 real FaceSwap",
                "• legacy V219 Comet generation: disabled",
            ])
        )
    finally:
        raise ApplicationHandlerStop


def bind_application(app: Any) -> bool:
    if not _is_app(app):
        return False
    if getattr(app, _HANDLER_FLAG, False):
        return True

    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v233_true_face_transfer as v234
    from neyrobot_prod.selfie_v208_nav_guard import clear_before_mode_callback

    # V234 gets the generation buttons before every compatibility handler.
    v234.bind_application(app)
    app.add_handler(CommandHandler("version", version_command), group=-4000)
    app.add_handler(CommandHandler("selfie_admin", v208._admin_command), group=-3999)
    app.add_handler(CommandHandler("diag_selfie_storage", v217.diagnostic), group=-3999)
    app.add_handler(CallbackQueryHandler(clear_before_mode_callback, pattern=r"^mode:(?:root|study|work|fun|medicine)$"), group=-3998)
    app.add_handler(CallbackQueryHandler(v219.public_callback, pattern=r"^(?:cs201:|act:fun:aiselfie(?:_upload|_last|_custom)?$|act:fun:as_preset_|fun:aiselfie$)"), group=-3997)
    video_filter = getattr(filters, "VIDEO", None)
    video_note_filter = getattr(filters, "VIDEO_NOTE", None)
    if video_filter is not None:
        combined = video_filter | video_note_filter if video_note_filter is not None else video_filter
        app.add_handler(MessageHandler(combined, v217.reject_non_photo_selfie), group=-3996)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, v219.public_media), group=-3995)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, v208._mode_router), group=-3994)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, v219.public_text), group=-3993)
    setattr(app, _HANDLER_FLAG, True)
    return True


def bind_runtime_apps() -> int:
    mod = _runtime()
    if mod is None:
        return 0
    count = 0
    seen: set[int] = set()
    for value in vars(mod).values():
        if id(value) in seen:
            continue
        seen.add(id(value))
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
    from neyrobot_prod import selfie_v233_true_face_transfer as v234

    install_builder_hook()
    patch_runtime()
    v234.install_async()
    bind_runtime_apps()
    if _STARTED:
        return
    _STARTED = True

    # Compatibility watchdog now repairs only toward V234, never toward V219.
    def worker() -> None:
        for _ in range(21600):
            with contextlib.suppress(Exception):
                patch_runtime()
                bind_runtime_apps()
            time.sleep(0.25)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v235-v234-compat").start()
    print("[neyrobot-prod] V235 compatibility owner: V219 UI -> V234 real FaceSwap", flush=True)


def install() -> None:
    install_async()


__all__ = ["VERSION", "version_command", "patch_runtime", "bind_application", "bind_runtime_apps", "install_builder_hook", "install_async", "install"]
