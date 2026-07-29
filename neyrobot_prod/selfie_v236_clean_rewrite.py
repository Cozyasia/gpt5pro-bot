# -*- coding: utf-8 -*-
"""V236 clean-room rewrite of the Celebrity Selfie mode.

This module owns the complete Telegram state machine for the mode. It does not
call legacy V219/V235 UI callbacks. The only reused production component is the
V234 provider pipeline (Google scene/body composition + PiAPI real FaceSwap).
"""
from __future__ import annotations

import contextlib
import sys
from typing import Any

VERSION = "v236-selfie-clean-rewrite-fullbody-faceswap-2026-07-29"
MODE_KEY = "cs236_active"
STATE_KEY = "cs236_state"
STATE_FACE = "face"
STATE_BODY = "body"
STATE_DESC = "description"
STATE_SCENE_IMAGE = "scene_image"
FULL_BODY_KEY = "cs233_user_full_body"
BOUND_FLAG = "_neyrobot_v236_clean_rewrite_bound"


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _photos(context: Any) -> list[bytes]:
    result: list[bytes] = []
    for item in context.user_data.get("cs201_user_photos") or []:
        raw = bytes(item or b"")
        if len(raw) > 1024:
            result.append(raw)
    return result[:3]


def _full_body(context: Any) -> bytes | None:
    raw = bytes(context.user_data.get(FULL_BODY_KEY) or b"")
    return raw if len(raw) > 1024 else None


def _reset(context: Any) -> None:
    keep = {
        key: context.user_data.get(key)
        for key in ()
    }
    for key in list(context.user_data.keys()):
        if key.startswith("cs201_") or key.startswith("cs215_") or key.startswith("cs233_") or key.startswith("cs234_") or key.startswith("cs236_") or key == "awaiting_ai_selfie_photo":
            context.user_data.pop(key, None)
    context.user_data.update({k: v for k, v in keep.items() if v is not None})
    context.user_data[MODE_KEY] = True


def _kb(rows: list[list[tuple[str, str]]]):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text, callback_data=data) for text, data in row]
        for row in rows
    ])


def _main_keyboard():
    return _kb([
        [("📸 Начать заново: 3 портрета + полный рост", "cs236:start")],
        [("🤳 Выбрать тип кадра", "cs236:shot_menu")],
        [("⭐ Выбрать героя", "cs236:country_menu")],
        [("🎬 Выбрать сцену", "cs236:scene_menu")],
        [("🚀 Создать изображение", "cs236:generate")],
        [("⬅️ Назад в Развлечения", "mode:fun")],
    ])


def _shot_keyboard():
    return _kb([
        [("🤳 Селфи", "cs236:shot:selfie")],
        [("📷 Фото от третьего лица", "cs236:shot:third")],
        [("⬅️ В меню режима", "cs236:open")],
    ])


def _country_keyboard():
    from neyrobot_prod import celebrity_selfie as base
    countries: dict[str, str] = {}
    for meta in base.CHARACTERS.values():
        country = str(meta.get("country") or "other")
        countries.setdefault(country, country.replace("_", " ").title())
    rows = [[(label, f"cs236:country:{code}")] for code, label in sorted(countries.items(), key=lambda x: x[1])]
    rows.append([("⬅️ В меню режима", "cs236:open")])
    return _kb(rows)


def _hero_keyboard(country: str):
    from neyrobot_prod import celebrity_selfie as base
    rows: list[list[tuple[str, str]]] = []
    for slug, meta in sorted(base.CHARACTERS.items(), key=lambda item: str(item[1].get("name") or item[0])):
        if str(meta.get("country") or "other") == country:
            rows.append([(str(meta.get("name") or slug), f"cs236:hero:{slug}")])
    rows.append([("⬅️ К странам", "cs236:country_menu")])
    return _kb(rows)


def _scene_source_keyboard():
    return _kb([
        [("🎬 Готовая сцена", "cs236:scene:preset_menu")],
        [("📝 Своя сцена по описанию", "cs236:scene:description")],
        [("🖼 Своя сцена по фото", "cs236:scene:image")],
        [("⬅️ В меню режима", "cs236:open")],
    ])


def _preset_keyboard():
    from neyrobot_prod import celebrity_selfie as base
    rows: list[list[tuple[str, str]]] = []
    for key, value in list(base.SCENES.items())[:30]:
        label = str(value[0] if isinstance(value, (tuple, list)) and value else key)
        rows.append([(label, f"cs236:preset:{key}")])
    rows.append([("⬅️ К выбору сцены", "cs236:scene_menu")])
    return _kb(rows)


def _status(context: Any) -> str:
    from neyrobot_prod import celebrity_selfie as base
    faces = len(_photos(context))
    body = "загружено" if _full_body(context) else "не загружено"
    shot_raw = str(context.user_data.get("cs215_shot_mode") or "")
    shot = "Селфи" if shot_raw == "selfie" else "Фото от третьего лица" if shot_raw == "third_person" else "не выбран"
    slug = str(context.user_data.get("cs201_character") or "")
    hero = str((base.CHARACTERS.get(slug) or {}).get("name") or "не выбран")
    scene = str(context.user_data.get("cs215_scene_label") or context.user_data.get("cs215_scene_text") or "не выбрана")
    if len(scene) > 90:
        scene = scene[:87] + "..."
    return (
        "🎭 AI-фото с героем — новый режим V236\n\n"
        "Порядок обязателен:\n"
        "1) три портрета лица;\n"
        "2) отдельное фото в полный рост;\n"
        "3) тип кадра;\n"
        "4) герой;\n"
        "5) сцена.\n\n"
        f"Портреты: {faces}/3\n"
        f"Фото в полный рост: {body}\n"
        f"Тип кадра: {shot}\n"
        f"Герой: {hero}\n"
        f"Сцена: {scene}\n\n"
        "Генерация выполняется только через Google Gemini + реальный PiAPI FaceSwap."
    )


async def _send_menu(message: Any, context: Any) -> None:
    await message.reply_text(_status(context), reply_markup=_main_keyboard())


async def _require_sequence(message: Any, context: Any) -> bool:
    if len(_photos(context)) != 3:
        await message.reply_text("📸 Сначала загрузите три портрета пользователя.", reply_markup=_main_keyboard())
        return False
    if not _full_body(context):
        context.user_data[STATE_KEY] = STATE_BODY
        await message.reply_text("🧍 Теперь пришлите отдельное чёткое фото в полный рост: от головы до обуви.")
        return False
    return True


async def _generate(update: Any, context: Any) -> bool:
    from neyrobot_prod import selfie_v234_hybrid_faceswap as provider
    message = getattr(update, "effective_message", None)
    if message is None:
        return False
    if not await _require_sequence(message, context):
        return False
    if not context.user_data.get("cs215_shot_mode"):
        await message.reply_text("Сначала выберите тип кадра.", reply_markup=_shot_keyboard())
        return False
    if not context.user_data.get("cs201_character"):
        await message.reply_text("Сначала выберите героя.", reply_markup=_country_keyboard())
        return False
    if not context.user_data.get("cs215_scene_mode"):
        await message.reply_text("Сначала выберите сцену.", reply_markup=_scene_source_keyboard())
        return False
    print("AI_SELFIE_V236_GENERATION_START provider=google_plus_piapi", flush=True)
    ok = await provider.generate(update, context, str(context.user_data.get("cs215_scene_text") or ""))
    print(f"AI_SELFIE_V236_GENERATION_DONE ok={bool(ok)}", flush=True)
    return bool(ok)


async def callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")
    with contextlib.suppress(Exception):
        await query.answer()

    if data in {"act:fun:aiselfie", "fun:aiselfie", "cs201:open", "cs236:open"} or data.startswith("act:fun:as_preset_"):
        context.user_data[MODE_KEY] = True
        await _send_menu(query.message, context)
        raise ApplicationHandlerStop

    if data.startswith("cs201:"):
        context.user_data[MODE_KEY] = True
        await query.message.reply_text("♻️ Старое меню отключено. Открываю полностью переписанный режим V236.")
        await _send_menu(query.message, context)
        raise ApplicationHandlerStop

    if not data.startswith("cs236:"):
        return

    context.user_data[MODE_KEY] = True
    user_id = int(query.from_user.id)
    runtime = _runtime()
    if runtime is not None:
        base._activate(runtime, context, user_id)

    if data == "cs236:start":
        _reset(context)
        context.user_data[STATE_KEY] = STATE_FACE
        await query.message.reply_text("📸 Портрет 1/3: пришлите чёткое фото анфас без фильтров, очков и размытия.")
    elif data == "cs236:shot_menu":
        if await _require_sequence(query.message, context):
            await query.message.reply_text("Выберите тип кадра:", reply_markup=_shot_keyboard())
    elif data.startswith("cs236:shot:"):
        if await _require_sequence(query.message, context):
            value = data.rsplit(":", 1)[-1]
            context.user_data["cs215_shot_mode"] = "selfie" if value == "selfie" else "third_person"
            await query.message.reply_text("✅ Тип кадра сохранён. Теперь выберите героя:", reply_markup=_country_keyboard())
    elif data == "cs236:country_menu":
        if await _require_sequence(query.message, context):
            await query.message.reply_text("Выберите страну героя:", reply_markup=_country_keyboard())
    elif data.startswith("cs236:country:"):
        country = data.rsplit(":", 1)[-1]
        await query.message.reply_text("Выберите героя:", reply_markup=_hero_keyboard(country))
    elif data.startswith("cs236:hero:"):
        slug = data.rsplit(":", 1)[-1]
        meta = base.CHARACTERS.get(slug)
        if not meta:
            await query.message.reply_text("Герой не найден. Выберите другого.", reply_markup=_country_keyboard())
        elif runtime is not None and not base._character_ready(runtime, slug):
            await query.message.reply_text(f"⚠️ Для героя «{meta.get('name', slug)}» не хватает трёх JPEG-референсов.")
        else:
            context.user_data["cs201_character"] = slug
            await query.message.reply_text(f"✅ Герой выбран: {meta.get('name', slug)}. Теперь выберите сцену:", reply_markup=_scene_source_keyboard())
    elif data == "cs236:scene_menu":
        if await _require_sequence(query.message, context):
            await query.message.reply_text("Выберите способ задания сцены:", reply_markup=_scene_source_keyboard())
    elif data == "cs236:scene:preset_menu":
        await query.message.reply_text("Выберите готовую сцену:", reply_markup=_preset_keyboard())
    elif data == "cs236:scene:description":
        context.user_data[STATE_KEY] = STATE_DESC
        await query.message.reply_text("📝 Опишите сцену одним сообщением: место, время суток, освещение и атмосферу.")
    elif data == "cs236:scene:image":
        context.user_data[STATE_KEY] = STATE_SCENE_IMAGE
        await query.message.reply_text("🖼 Пришлите одно фото нужной сцены. Оно будет использовано только как референс места.")
    elif data.startswith("cs236:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if not preset:
            await query.message.reply_text("Сцена не найдена.", reply_markup=_preset_keyboard())
        else:
            label = str(preset[0] if isinstance(preset, (tuple, list)) else key)
            text = str(preset[1] if isinstance(preset, (tuple, list)) and len(preset) > 1 else preset)
            context.user_data["cs215_scene_mode"] = "preset"
            context.user_data["cs215_scene_text"] = text
            context.user_data["cs215_scene_label"] = label
            context.user_data.pop("cs215_scene_image", None)
            await _generate(update, context)
    elif data == "cs236:generate":
        await _generate(update, context)
    else:
        await _send_menu(query.message, context)
    raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    if not context.user_data.get(MODE_KEY):
        return
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if message is None or user is None:
        return
    state = str(context.user_data.get(STATE_KEY) or "")
    raw, url = await base._download_photo_message(message)
    if not raw:
        raise ApplicationHandlerStop

    if state == STATE_FACE:
        values = _photos(context)
        if len(values) >= 3:
            values = []
        values.append(bytes(raw))
        context.user_data["cs201_user_photos"] = values
        with contextlib.suppress(Exception):
            runtime = _runtime()
            if runtime is not None:
                base._cache_photo(runtime, int(user.id), raw, url)
        count = len(values)
        print(f"AI_SELFIE_V236_FACE_ACCEPTED count={count}", flush=True)
        if count == 1:
            await message.reply_text("✅ Портрет 1/3 принят. Пришлите портрет 2/3 с лёгким поворотом головы.")
        elif count == 2:
            await message.reply_text("✅ Портрет 2/3 принят. Пришлите портрет 3/3 с другого естественного ракурса.")
        else:
            context.user_data[STATE_KEY] = STATE_BODY
            await message.reply_text("✅ Все 3/3 портрета приняты.\n\n🧍 Теперь обязательно пришлите отдельное фото в полный рост — от головы до обуви, при хорошем освещении.")
    elif state == STATE_BODY:
        context.user_data[FULL_BODY_KEY] = bytes(raw)
        context.user_data.pop(STATE_KEY, None)
        print("AI_SELFIE_V236_FULL_BODY_ACCEPTED", flush=True)
        await message.reply_text("✅ Фото в полный рост принято. Теперь выберите тип кадра:", reply_markup=_shot_keyboard())
    elif state == STATE_SCENE_IMAGE:
        context.user_data["cs215_scene_image"] = v215._compact_scene(raw)
        context.user_data["cs215_scene_mode"] = "image"
        context.user_data["cs215_scene_text"] = "inside the uploaded location, preserving its architecture, perspective and lighting"
        context.user_data["cs215_scene_label"] = "🖼 Загруженная сцена"
        context.user_data.pop(STATE_KEY, None)
        print("AI_SELFIE_V236_SCENE_IMAGE_ACCEPTED", flush=True)
        await message.reply_text("✅ Фото сцены принято. Можно запускать генерацию.", reply_markup=_main_keyboard())
    else:
        await message.reply_text("Это фото не ожидалось. Используйте кнопки нового режима.", reply_markup=_main_keyboard())
    raise ApplicationHandlerStop


async def text(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    if not context.user_data.get(MODE_KEY):
        return
    message = getattr(update, "effective_message", None)
    if message is None:
        return
    value = str(getattr(message, "text", "") or "").strip()
    if str(context.user_data.get(STATE_KEY) or "") == STATE_DESC and value:
        context.user_data["cs215_scene_mode"] = "description"
        context.user_data["cs215_scene_text"] = value
        context.user_data["cs215_scene_label"] = "📝 Своя сцена"
        context.user_data.pop("cs215_scene_image", None)
        context.user_data.pop(STATE_KEY, None)
        print("AI_SELFIE_V236_SCENE_DESCRIPTION_ACCEPTED", flush=True)
        await message.reply_text("✅ Описание сцены сохранено. Можно запускать генерацию.", reply_markup=_main_keyboard())
    else:
        await message.reply_text("Используйте кнопки нового режима V236.", reply_markup=_main_keyboard())
    raise ApplicationHandlerStop


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)):
        return False
    if getattr(app, BOUND_FLAG, False):
        return True
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^(cs236:|cs201:|act:fun:aiselfie|fun:aiselfie|act:fun:as_preset_)"), group=-70000)
    app.add_handler(MessageHandler(filters.PHOTO, media), group=-70000)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text), group=-70000)
    setattr(app, BOUND_FLAG, True)
    print("AI_SELFIE_V236_CLEAN_OWNER_BOUND group=-70000", flush=True)
    return True


__all__ = ["VERSION", "bind_application", "callback", "media", "text"]
