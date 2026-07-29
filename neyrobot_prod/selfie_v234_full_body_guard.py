# -*- coding: utf-8 -*-
"""V234 media guard: after portrait 3/3, immediately request full-body photo."""
from __future__ import annotations

import contextlib
from typing import Any

_FLAG = "_neyrobot_v234_portrait_then_body_guard"


async def portrait_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v233_body_face_transplant as v233

    if context.user_data.get(v233._AWAIT_FULL_BODY):
        return
    runtime = v217._runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, user.id):
        return
    photos = v217._photos(context)
    if not context.user_data.get("awaiting_ai_selfie_photo") and not (0 < len(photos) < v217.USER_REFS):
        return

    raw, url = await base._download_photo_message(message)
    if not raw:
        return
    base._activate(runtime, context, user.id)
    count = v217._append_photo(context, raw)
    with contextlib.suppress(Exception):
        base._cache_photo(runtime, user.id, raw, url)

    if count < v217.USER_REFS:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await message.reply_text(v217._instruction_for_next(count))
    else:
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        context.user_data[v233._AWAIT_FULL_BODY] = True
        context.user_data.pop(v233._FULL_BODY_KEY, None)
        await message.reply_text(
            "✅ Все 3/3 портрета приняты.\n\n"
            "🧍 Теперь обязательно пришлите одно чёткое фото в полный рост. Всё тело должно быть видно от головы до обуви, без зеркального широкоугольного искажения, в обычной одежде и при хорошем освещении. После этого бот предложит выбрать героя."
        )
    raise ApplicationHandlerStop


async def full_body_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v233_body_face_transplant as v233

    if not context.user_data.get(v233._AWAIT_FULL_BODY):
        return
    message = getattr(update, "effective_message", None)
    if message is None:
        return
    raw, _url = await base._download_photo_message(message)
    if not raw:
        return
    context.user_data[v233._FULL_BODY_KEY] = bytes(raw)
    context.user_data.pop(v233._AWAIT_FULL_BODY, None)
    await message.reply_text(
        "✅ Фото в полный рост принято. Оно будет использоваться для комплекции, пропорций тела, одежды и позы. Теперь выберите страну и героя:",
        reply_markup=v208._country_kb(base, v233._runtime()),
    )
    raise ApplicationHandlerStop


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)):
        return False
    if getattr(app, _FLAG, False):
        return True
    from telegram.ext import MessageHandler, filters
    # This group runs before V217 and V233 media handlers, so portrait 3/3 can
    # deterministically transition into the mandatory full-body step.
    app.add_handler(MessageHandler(filters.PHOTO, full_body_media), group=-32001)
    app.add_handler(MessageHandler(filters.PHOTO, portrait_media), group=-32000)
    setattr(app, _FLAG, True)
    return True


__all__ = ["portrait_media", "full_body_media", "bind_application"]
