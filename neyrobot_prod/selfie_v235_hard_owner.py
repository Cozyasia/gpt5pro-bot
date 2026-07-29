# -*- coding: utf-8 -*-
"""V235 hard owner for the celebrity-selfie flow.

This module does not rely on import-time aliases alone. It owns the registered
PTB callbacks, requires a full-body image after portrait 3/3, and routes every
successful generation through V234 Google + PiAPI FaceSwap.
"""
from __future__ import annotations

import contextlib
from typing import Any

VERSION = "v235-selfie-hard-owner-fullbody-faceswap-2026-07-29"
AWAIT_FULL_BODY = "cs234_await_full_body"
FULL_BODY_KEY = "cs233_user_full_body"
BOUND_FLAG = "_neyrobot_v235_hard_owner_bound"


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v219_triref_scene_owner as legacy
    return legacy._runtime()


def _faces(context: Any) -> list[bytes]:
    from neyrobot_prod import selfie_v219_triref_scene_owner as legacy
    return legacy._photos(context)


def _full_body(context: Any) -> bytes | None:
    raw = bytes(context.user_data.get(FULL_BODY_KEY) or b"")
    return raw if len(raw) > 1024 else None


def _clear_body(context: Any) -> None:
    context.user_data.pop(FULL_BODY_KEY, None)
    context.user_data.pop(AWAIT_FULL_BODY, None)


async def _request_body(message: Any, context: Any) -> None:
    context.user_data.pop("awaiting_ai_selfie_photo", None)
    context.user_data[AWAIT_FULL_BODY] = True
    await message.reply_text(
        "✅ Все 3/3 портрета приняты.\n\n"
        "🧍 Теперь обязательно пришлите одно отдельное фото в полный рост. "
        "Человек должен быть виден от головы до обуви, без зеркального широкоугольного искажения, "
        "в обычной одежде и при хорошем освещении. До загрузки этого фото выбор героя и генерация заблокированы."
    )


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import selfie_v234_hybrid_faceswap as hybrid
    message = getattr(update, "effective_message", None)
    if not _full_body(context):
        if message is not None:
            await _request_body(message, context)
        return False
    return await hybrid.generate(update, context, scene)


async def public_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v216_admin_upload_priority as v216
    from neyrobot_prod import selfie_v219_triref_scene_owner as legacy

    runtime = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, int(user.id)):
        return

    if any(context.user_data.get(key) for key in ("cs212_admin_upload", "ss205_admin_upload", "cs202_admin_upload", "cs201_admin_upload")):
        await v216.media_router(update, context)
        raise ApplicationHandlerStop

    raw, url = await base._download_photo_message(message)
    if not raw:
        return

    if context.user_data.get("cs215_await_scene_image"):
        context.user_data["cs215_scene_image"] = v215._compact_scene(raw)
        context.user_data["cs215_scene_mode"] = v215.SCENE_IMAGE
        context.user_data["cs215_scene_text"] = "inside the uploaded real location, preserving its exact visual environment"
        context.user_data["cs215_scene_label"] = "🖼 Загруженная сцена"
        context.user_data.pop("cs215_await_scene_image", None)
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        await message.reply_text(
            "✅ Фото сцены принято как отдельный структурный референс. Нажмите «Создать изображение».",
            reply_markup=v215._ready_scene_keyboard(runtime),
        )
        raise ApplicationHandlerStop

    if context.user_data.get(AWAIT_FULL_BODY):
        context.user_data[FULL_BODY_KEY] = bytes(raw)
        context.user_data.pop(AWAIT_FULL_BODY, None)
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        print("AI_SELFIE_V235_FULL_BODY_ACCEPTED", flush=True)
        await message.reply_text(
            "✅ Фото в полный рост принято. Оно будет использоваться только для комплекции, пропорций тела, одежды и позы. "
            "Теперь выберите тип кадра:",
            reply_markup=v215._shot_keyboard(runtime),
        )
        raise ApplicationHandlerStop

    photos = _faces(context)
    if not context.user_data.get("awaiting_ai_selfie_photo") and not (0 < len(photos) < legacy.USER_REFS):
        return

    base._activate(runtime, context, int(user.id))
    count = legacy._append_photo(context, raw)
    with contextlib.suppress(Exception):
        base._cache_photo(runtime, int(user.id), raw, url)

    if count == 1:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await message.reply_text("✅ Селфи 1/3 принято. Пришлите селфи 2/3 с лёгким поворотом головы на 15–30°.")
    elif count == 2:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await message.reply_text("✅ Селфи 2/3 принято. Пришлите селфи 3/3: ещё один естественный ракурс при хорошем освещении.")
    else:
        await _request_body(message, context)
    raise ApplicationHandlerStop


async def public_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_v219_triref_scene_owner as legacy

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")

    if data in {"cs201:photo", "act:fun:aiselfie_upload", "cs201:reuse:photos", "cs201:last", "act:fun:aiselfie_last"}:
        _clear_body(context)

    requires_body = (
        data in {
            "cs201:shot_menu", "cs201:reuse:shot", "cs201:characters", "act:fun:aiselfie_custom",
            "cs201:reuse:hero", "cs201:scene_sources", "cs201:reuse:scene", "cs201:generate_current",
            "cs201:reuse:repeat",
        }
        or data.startswith("cs201:shot:")
        or data.startswith("cs201:country:")
        or data.startswith("cs201:character:")
        or data.startswith("cs201:scene_mode:")
        or data.startswith("cs201:preset:")
        or data.startswith("act:fun:as_preset_")
    )
    if requires_body and len(_faces(context)) == 3 and not _full_body(context):
        with contextlib.suppress(Exception):
            await query.answer()
        await _request_body(query.message, context)
        raise ApplicationHandlerStop

    # The legacy callback remains the UI renderer, but all generation globals are
    # forced to the hard owner before every call.
    legacy.generate = generate
    legacy.public_callback.__globals__["generate"] = generate
    await legacy.public_callback(update, context)


async def public_text(update: Any, context: Any) -> None:
    from neyrobot_prod import selfie_v219_triref_scene_owner as legacy
    legacy.generate = generate
    legacy.public_text.__globals__["generate"] = generate
    await legacy.public_text(update, context)


def _take_over_registered_handlers(app: Any) -> int:
    replaced = 0
    handlers = getattr(app, "handlers", {}) or {}
    groups = handlers.values() if isinstance(handlers, dict) else []
    for group in groups:
        for handler in list(group or []):
            callback = getattr(handler, "callback", None)
            name = getattr(callback, "__name__", "")
            module = getattr(callback, "__module__", "")
            if "selfie_v219_triref_scene_owner" not in module:
                continue
            if name == "public_callback":
                handler.callback = public_callback
                replaced += 1
            elif name == "public_media":
                handler.callback = public_media
                replaced += 1
            elif name == "public_text":
                handler.callback = public_text
                replaced += 1
    return replaced


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)):
        return False
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters

    # Replace callbacks already registered by V219 and also install an earlier,
    # explicit owner layer. ApplicationHandlerStop prevents legacy fall-through.
    replaced = _take_over_registered_handlers(app)
    if not getattr(app, BOUND_FLAG, False):
        app.add_handler(CallbackQueryHandler(public_callback, pattern=r"^(cs201:|act:fun:aiselfie|fun:aiselfie|act:fun:as_preset_)"), group=-60000)
        app.add_handler(MessageHandler(filters.PHOTO, public_media), group=-60000)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, public_text), group=-60000)
        setattr(app, BOUND_FLAG, True)
    print(f"AI_SELFIE_V235_HANDLER_TAKEOVER replaced={replaced}", flush=True)
    return True


def patch_runtime() -> None:
    from neyrobot_prod import selfie_v219_triref_scene_owner as legacy
    from neyrobot_prod import selfie_v233_body_face_transplant as v233
    from neyrobot_prod import selfie_v234_hybrid_faceswap as hybrid
    legacy.generate = generate
    legacy.public_callback.__globals__["generate"] = generate
    legacy.public_text.__globals__["generate"] = generate
    legacy._comet_generate = hybrid._piapi_task  # impossible legacy signature: fail loudly if reached
    v233.generate = generate


__all__ = ["VERSION", "generate", "public_callback", "public_media", "public_text", "bind_application", "patch_runtime"]
