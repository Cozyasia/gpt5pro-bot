# -*- coding: utf-8 -*-
"""V257 guaranteed runtime owner for AI Selfie.

The filename is retained because secret_loader.py already imports it from the
stable production bootstrap. V257 is the sole production generation owner while
V219 remains the stable Telegram navigation/storage contract.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v257-consolidated-ai-selfie-owner-2026-08-09"
_HANDLER_FLAG = "_selfie_v257_consolidated_owner_bound"
_BUILDER_FLAG = "_selfie_v257_consolidated_builder_hooked"
_STARTED = False
_ORIGINAL_CALLBACK: Any | None = None


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _is_app(value: Any) -> bool:
    return value is not None and callable(getattr(value, "add_handler", None)) and isinstance(getattr(value, "handlers", None), dict)


def _upload_log(stage: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={value!r}" for key, value in fields.items())
    print(f"[neyrobot-prod] AI_SELFIE_V257_UPLOAD stage={stage} {suffix}", flush=True)


async def _photo_callback(update: Any, context: Any) -> None:
    """Own only photo-upload entry actions; delegate all other V219 navigation."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")
    if data not in {"cs201:photo", "act:fun:aiselfie_upload", "cs201:reuse:photos", "cs201:last", "act:fun:aiselfie_last"}:
        original = _ORIGINAL_CALLBACK
        if callable(original):
            await original(update, context)
        return

    with contextlib.suppress(Exception):
        await query.answer()
    try:
        runtime = _runtime()
        if runtime is not None:
            base._activate(runtime, context, int(query.from_user.id))
        if data in {"cs201:photo", "act:fun:aiselfie_upload", "cs201:reuse:photos"}:
            v219._reset_photos(context)
            context.user_data["awaiting_ai_selfie_photo"] = True
            await query.message.reply_text(
                "📸 Фото 1/3 — телосложение и возраст.\n"
                "Пришлите чёткое фото анфас или по пояс без фильтров. Первые два фото нужны модели только для возраста, роста, комплекции и пропорций тела; личность по ним не переносится."
            )
        else:
            cached = base._cached_photo(runtime, int(query.from_user.id)) if runtime is not None else None
            v219._reset_photos(context, cached if cached else None)
            context.user_data["awaiting_ai_selfie_photo"] = True
            if cached:
                await query.message.reply_text(
                    "✅ Последнее фото принято как фото 1/3 для телосложения.\n"
                    "Пришлите фото 2/3 с другим естественным ракурсом — оно также используется только для возраста, роста и комплекции."
                )
            else:
                await query.message.reply_text("Последнего фото нет. Пришлите фото 1/3 анфас — оно нужно для возраста, роста и комплекции.")
    finally:
        raise ApplicationHandlerStop


async def _photo_media(update: Any, context: Any) -> None:
    """Single high-priority owner for AI Selfie photo ingestion.

    The handler intentionally runs before diagnostic/legacy image handlers. When
    the separate Face Swap diagnostic is active it yields immediately so that
    diagnostic mode can own its own source/target uploads.
    """
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    if str(context.user_data.get("faceswap_diag_state") or "") in {"source", "target", "running"}:
        return

    runtime = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, int(user.id)):
        return

    if any(context.user_data.get(key) for key in ("cs212_admin_upload", "ss205_admin_upload", "cs202_admin_upload", "cs201_admin_upload")):
        from neyrobot_prod import selfie_v216_admin_upload_priority as v216
        await v216.media_router(update, context)
        raise ApplicationHandlerStop

    try:
        raw, url = await base._download_photo_message(message)
        if not raw:
            return
        _upload_log("downloaded", user_id=int(user.id), bytes=len(raw), awaiting_scene=bool(context.user_data.get("cs215_await_scene_image")), current_refs=len(v219._photos(context)))

        if context.user_data.get("cs215_await_scene_image"):
            context.user_data["cs215_scene_image"] = v215._compact_scene(raw)
            context.user_data["cs215_scene_mode"] = v215.SCENE_IMAGE
            context.user_data["cs215_scene_text"] = "inside the uploaded real location, preserving its exact visual environment"
            context.user_data["cs215_scene_label"] = "🖼 Загруженная сцена"
            context.user_data.pop("cs215_await_scene_image", None)
            context.user_data.pop("awaiting_ai_selfie_photo", None)
            _upload_log("scene_saved", user_id=int(user.id), bytes=len(context.user_data["cs215_scene_image"]))
            await message.reply_text("✅ Фото сцены принято как отдельный структурный референс. Нажмите «Создать изображение».", reply_markup=v215._ready_scene_keyboard(runtime))
            raise ApplicationHandlerStop

        photos = v219._photos(context)
        if not context.user_data.get("awaiting_ai_selfie_photo") and not (0 < len(photos) < v219.USER_REFS):
            return

        base._activate(runtime, context, int(user.id))
        count = v219._append_photo(context, raw)
        with contextlib.suppress(Exception):
            base._cache_photo(runtime, int(user.id), raw, url)
        _upload_log("reference_saved", user_id=int(user.id), count=count, bytes=len(raw))

        if count == 1:
            context.user_data["awaiting_ai_selfie_photo"] = True
            await message.reply_text(
                "✅ Фото 1/3 принято для возраста и телосложения.\n"
                "Пришлите фото 2/3 с лёгким поворотом головы или в другом естественном ракурсе. Оно также используется только для комплекции и пропорций."
            )
        elif count == 2:
            context.user_data["awaiting_ai_selfie_photo"] = True
            await message.reply_text(
                "✅ Фото 2/3 принято для возраста и телосложения.\n\n"
                "🧬 Теперь пришлите фото 3/3 — главный источник лица. Нужен чёткий портрет анфас, без фильтров, очков и сильных теней, лицо крупно и полностью видно. После полной генерации сцены именно это лицо будет отдельно перенесено через обязательный Face Swap."
            )
        else:
            context.user_data.pop("awaiting_ai_selfie_photo", None)
            await message.reply_text(
                "✅ Все 3/3 фото приняты.\n"
                "Фото 1–2: возраст, рост, телосложение и пропорции.\n"
                "Фото 3: единственный источник личности лица для финального переноса после генерации сцены.\n"
                "Теперь выберите тип кадра:",
                reply_markup=v215._shot_keyboard(runtime),
            )
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        _upload_log("failed", user_id=int(user.id), error_type=type(exc).__name__, error=str(exc)[:900])
        with contextlib.suppress(Exception):
            await message.reply_text(f"❌ Не удалось принять фотографию. Причина: {type(exc).__name__}. Попробуйте отправить её ещё раз.")
    finally:
        # Once this handler has accepted responsibility for an active AI Selfie
        # upload, no lower-priority legacy photo handler may process the same update.
        raise ApplicationHandlerStop


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
                "AI-селфи V257: Gemini сцена+герой+тело → строгий Person A lock → один PiAPI Face Swap с фото №3 → edge-only integration.",
                "Фото 1–2: возраст/телосложение. Фото 3: единственный источник личности лица.",
                "Второй PiAPI: off. Gemini после PiAPI: off. Literal fallback: off.",
                "Логи Render: AI_SELFIE_V257 trace=...",
            ])
        )
    finally:
        raise ApplicationHandlerStop


def patch_runtime() -> bool:
    global _ORIGINAL_CALLBACK
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import celebrity_selfie_v204 as generator
    from neyrobot_prod import selfie_commands_v206 as commands
    from neyrobot_prod import selfie_runtime_v207 as legacy_runtime
    from neyrobot_prod import selfie_storage_v205 as storage
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    from neyrobot_prod import selfie_v257_consolidated_runtime as terminal

    if _ORIGINAL_CALLBACK is None and v219.public_callback is not _photo_callback:
        _ORIGINAL_CALLBACK = v219.public_callback

    v219.generate = terminal.generate
    with contextlib.suppress(Exception):
        v219.public_callback.__globals__["generate"] = terminal.generate
    v219.public_callback = _photo_callback
    v219.public_media = _photo_media

    for module in (v217, v208, v209, generator, commands, legacy_runtime, storage, v219, v229, terminal):
        with contextlib.suppress(Exception):
            module.VERSION = VERSION

    base.callback = _photo_callback
    base.media_entry = _photo_media
    base._generate = terminal.generate
    v208._public_callback = _photo_callback
    v208._public_media = _photo_media
    v208._generate = terminal.generate
    v217.public_callback = _photo_callback
    v217.public_media = _photo_media
    v217.generate = terminal.generate

    mod = _runtime()
    if mod is not None:
        mod.CELEBRITY_SELFIE_VERSION = VERSION
        mod.AI_SELFIE_RUNTIME_VERSION = VERSION
        mod.CELEBRITY_SELFIE_ROUTE = "v257-consolidated-single-piapi-photo3-identity"
        mod.SELFIE_STORAGE_VERSION = VERSION
        mod.SELFIE_COMMANDS_VERSION = VERSION
        mod.AI_SELFIE_USER_REFERENCES = 3
        mod.AI_SELFIE_BODY_REFERENCES = 2
        mod.AI_SELFIE_TERMINAL_FACE_REFERENCE = "photo_3_only"
        mod.AI_SELFIE_HERO_REFERENCES = 3
        mod.AI_SELFIE_ALLOW_COMPOSITION_FALLBACK = False
        mod.AI_SELFIE_SECOND_FACE_SWAP = False
        mod.AI_SELFIE_GEMINI_AFTER_PIAPI = False
        mod.AI_SELFIE_LITERAL_FACE_FALLBACK = False
        mod.AI_SELFIE_TRACE_PREFIX = "AI_SELFIE_V257"
    return True


def bind_application(app: Any) -> bool:
    if not _is_app(app):
        return False
    if getattr(app, _HANDLER_FLAG, False):
        return True

    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod.selfie_v208_nav_guard import clear_before_mode_callback

    patch_runtime()
    app.add_handler(CommandHandler("version", version_command), group=-910120)
    app.add_handler(CommandHandler("selfie_admin", v208._admin_command), group=-910119)
    app.add_handler(CommandHandler("diag_selfie_storage", v217.diagnostic), group=-910119)
    app.add_handler(CallbackQueryHandler(clear_before_mode_callback, pattern=r"^mode:(?:root|study|work|fun|medicine)$"), group=-910118)
    app.add_handler(CallbackQueryHandler(_photo_callback, pattern=r"^(?:cs201:|act:fun:aiselfie(?:_upload|_last|_custom)?$|act:fun:as_preset_|fun:aiselfie$)"), group=-910117)
    video_filter = getattr(filters, "VIDEO", None)
    video_note_filter = getattr(filters, "VIDEO_NOTE", None)
    if video_filter is not None:
        combined = video_filter | video_note_filter if video_note_filter is not None else video_filter
        app.add_handler(MessageHandler(combined, v217.reject_non_photo_selfie), group=-910116)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _photo_media), group=-910115)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, v208._mode_router), group=-910114)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, v219.public_text), group=-910113)
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
        patch_runtime()
        app = original(self, *args, **kwargs)
        patch_runtime()
        bind_application(app)
        print(f"[neyrobot-prod] V257 consolidated AI Selfie owner bound version={VERSION}", flush=True)
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

    # Legacy modules install during main.py import. Reassert V257 for a bounded
    # startup window, then stop. There is no permanent production rebinding loop.
    def worker() -> None:
        for _ in range(300):
            with contextlib.suppress(Exception):
                patch_runtime()
                bind_runtime_apps()
            time.sleep(0.2)
        print(f"[neyrobot-prod] V257 owner startup stabilization complete version={VERSION}", flush=True)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v257-owner").start()
    print(f"[neyrobot-prod] V257 consolidated AI Selfie owner installed version={VERSION}", flush=True)


def install() -> None:
    install_async()


__all__ = ["VERSION", "version_command", "patch_runtime", "bind_application", "bind_runtime_apps", "install_builder_hook", "install_async", "install"]
