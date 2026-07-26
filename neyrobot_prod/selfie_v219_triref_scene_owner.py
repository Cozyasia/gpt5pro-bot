# -*- coding: utf-8 -*-
"""V219 canonical Celebrity Selfie owner.

Fixes the production mismatch between the three-user-reference pipeline and the
older two-photo V215 UI. It also gives an uploaded scene image absolute routing
priority, so it cannot fall through to the bot's generic photo menu.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from typing import Any

VERSION = "v219-selfie-triref-scene-owner-2026-07-27"
USER_REFS = 3
HERO_REFS = 3
_HANDLER_FLAG = "_selfie_v219_triref_scene_owner_bound"
_BUILDER_FLAG = "_selfie_v219_builder_hooked"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _photos(context: Any) -> list[bytes]:
    out: list[bytes] = []
    for item in context.user_data.get("cs201_user_photos") or []:
        raw = bytes(item or b"")
        if len(raw) > 1024:
            out.append(raw)
    return out[:USER_REFS]


def _reset_photos(context: Any, first: bytes | None = None) -> None:
    values = [bytes(first)] if first and len(bytes(first)) > 1024 else []
    context.user_data["cs201_user_photos"] = values
    context.user_data["cs201_user_photo_step"] = len(values)
    context.user_data["cs201_user_photo_ready"] = len(values) == USER_REFS


def _append_photo(context: Any, raw: bytes) -> int:
    values = _photos(context)
    if len(values) >= USER_REFS:
        values = []
    data = bytes(raw or b"")
    if len(data) < 1024:
        raise ValueError("empty selfie")
    values.append(data)
    context.user_data["cs201_user_photos"] = values
    context.user_data["cs201_user_photo_step"] = len(values)
    context.user_data["cs201_user_photo_ready"] = len(values) == USER_REFS
    return len(values)


def _main_keyboard(runtime: Any):
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("📸 Загрузить 3 фото пользователя", callback_data="cs201:photo")],
        [runtime.InlineKeyboardButton("✅ Последнее фото + добавить ещё 2", callback_data="cs201:last")],
        [runtime.InlineKeyboardButton("🤳 / 📷 Выбрать тип кадра", callback_data="cs201:shot_menu")],
        [runtime.InlineKeyboardButton("⭐ Выбрать героя", callback_data="cs201:characters")],
        [runtime.InlineKeyboardButton("⬅️ Назад в Развлечения", callback_data="mode:fun")],
    ])


def _status_text(context: Any) -> str:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    photos = len(_photos(context))
    shot = str(context.user_data.get("cs215_shot_mode") or "")
    slug = str(context.user_data.get("cs201_character") or "")
    hero = str((base.CHARACTERS.get(slug) or {}).get("name") or "не выбран")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    return (
        "🎭 AI-фото с героем\n\n"
        "Порядок: 1) три фото пользователя; 2) тип кадра; 3) герой; "
        "4) готовая сцена, своя сцена по описанию или своя сцена по фото.\n\n"
        f"Фото пользователя: {photos}/{USER_REFS}\n"
        f"Тип кадра: {v215._shot_label(shot) if shot else 'не выбран'}\n"
        f"Герой: {hero}\n"
        f"Сцена: {v215._scene_mode_label(scene_mode)}"
    )


def _clear_wait_flags(context: Any) -> None:
    for key in ("cs201_wait_custom_scene", "cs215_wait_scene_text", "cs215_await_scene_image", "awaiting_ai_selfie_prompt", "ai_selfie_preset_prompt"):
        context.user_data.pop(key, None)


def _scene_ready(context: Any) -> bool:
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    mode = str(context.user_data.get("cs215_scene_mode") or "")
    if mode in {v215.SCENE_PRESET, v215.SCENE_DESCRIPTION}:
        return bool(str(context.user_data.get("cs215_scene_text") or "").strip())
    if mode == v215.SCENE_IMAGE:
        return len(bytes(context.user_data.get("cs215_scene_image") or b"")) > 1024
    return False


def _prompt(name: str, scene: str, aspect: str, shot_mode: str, has_scene_image: bool) -> str:
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    if shot_mode == v215.SHOT_THIRD_PERSON:
        shot = "SHOT MODE: THIRD-PERSON JOINT PHOTO. Another person takes the photograph. Do not show a phone, selfie stick, camera interface or oversized foreground hand."
    else:
        shot = "SHOT MODE: FRONT-CAMERA SELFIE POV. The image is the front-camera result itself. The phone must remain outside the frame and must not be visible."
    scene_rule = f"SCENE REQUEST: {scene or 'a natural premium real-world environment'}. "
    if has_scene_image:
        scene_rule += "REFERENCE 7 is the authoritative uploaded location reference. Preserve its architecture, layout, furniture, perspective, lighting direction and atmosphere. Ignore identities of any people visible in it and place only PERSON A and PERSON B. "
    return (
        f"Create one photorealistic vertical image with exactly two principal people. Aspect ratio {aspect}. {shot} {scene_rule}"
        "IDENTITY FIDELITY FOR BOTH PEOPLE IS THE HIGHEST PRIORITY. PERSON A IS THE USER. REFERENCES 1, 2 and 3 are three photos of the SAME USER from different angles. "
        "Use all three as equal authoritative identity anchors. Preserve exact facial geometry, apparent age, head shape, eye spacing and shape, eyebrows, nose, mouth, cheeks, jawline, chin, beard, hairline, skin tone, body build and natural asymmetry. "
        "Do not beautify, slim, rejuvenate, age-shift, change ethnicity, average the face or replace the user with a generic similar person. "
        f"PERSON B IS {name}. REFERENCES 4, 5 and 6 are three photos of that SAME person and define PERSON B's identity. "
        "Give PERSON A and PERSON B exactly equal identity priority and equal facial fidelity. Keep them separate; never merge, swap, average, duplicate or transfer features. "
        "Use realistic anatomy, skin texture, lighting, perspective and scale. No text, logos, watermarks or interface elements. The result is fictional AI-generated fan content and is not evidence of a real meeting or endorsement."
    )


async def _comet_generate(user_images: list[bytes], slug: str, scene: str, shot_mode: str, scene_image: bytes | None) -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen
    from neyrobot_prod import selfie_v213_user_identity_lock as identity
    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    refs = base._reference_paths(runtime, slug)
    if len(user_images) != USER_REFS or len(refs) != HERO_REFS:
        raise RuntimeError(f"user photos={len(user_images)}/{USER_REFS}, character refs={len(refs)}/{HERO_REFS}")
    prepared = [identity._prepare_original(base, runtime, raw) for raw in user_images]
    prepared.extend(identity._prepare_original(base, runtime, path.read_bytes()) for path in refs)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    if has_scene_image:
        prepared.append(identity._prepare_original(base, runtime, bytes(scene_image or b"")))
    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    prompt = _prompt(name, scene, base._aspect_ratio(), shot_mode, has_scene_image)
    labels = [
        "REFERENCE 1 — USER FRONT / IDENTITY ANCHOR A", "REFERENCE 2 — USER ANGLE / IDENTITY ANCHOR B", "REFERENCE 3 — USER ANGLE / IDENTITY ANCHOR C",
        f"REFERENCE 4 — {name} PORTRAIT A", f"REFERENCE 5 — {name} PORTRAIT B", f"REFERENCE 6 — {name} PORTRAIT C",
    ]
    if has_scene_image:
        labels.append("REFERENCE 7 — USER-UPLOADED LOCATION: SCENE STRUCTURE ONLY, NOT IDENTITY")
    key = gen._comet_key()
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")
    base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    import httpx
    errors: list[str] = []
    timeout_value = max(300.0, float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300") or 300))
    timeout = httpx.Timeout(timeout_value, connect=40.0, read=timeout_value, write=180.0, pool=40.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for model in gen._models():
            for camel, compatibility in ((True, False), (False, False), (True, True), (False, True)):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, (data, mime) in zip(labels, prepared):
                    parts.append({"text": label})
                    parts.append({"inlineData": {"mimeType": mime, "data": data}} if camel else {"inline_data": {"mime_type": mime, "data": data}})
                config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
                if not compatibility:
                    config["imageConfig"] = {"aspectRatio": base._aspect_ratio(), "imageSize": base._image_size()}
                try:
                    response = await client.post(f"{base_url}/v1beta/models/{model}:generateContent", headers=headers, json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config})
                    if response.status_code >= 400:
                        errors.append(f"{model}: HTTP {response.status_code}: {response.text[:350]}")
                        continue
                    output = gen._extract_final_image(response.json())
                    if output:
                        return output
                    errors.append(f"{model}: response contained no final image")
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Comet V219 generation failed: " + " | ".join(errors[-8:]))


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    runtime = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False
    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    photos = _photos(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or context.user_data.get("cs215_scene_text") or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == v215.SCENE_IMAGE else None
    if not meta:
        await delivery._safe_text(message, "Сначала выберите страну и героя.")
        return False
    if not base._character_ready(runtime, slug):
        await delivery._safe_text(message, f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(runtime, slug)}.")
        return False
    if len(photos) != USER_REFS:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await delivery._safe_text(message, f"Нужны три фото пользователя. Сейчас получено {len(photos)}/{USER_REFS}.")
        return False
    if shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON}:
        await message.reply_text("Сначала выберите тип кадра:", reply_markup=v215._shot_keyboard(runtime))
        return False
    if scene_mode not in {v215.SCENE_PRESET, v215.SCENE_DESCRIPTION, v215.SCENE_IMAGE} or not _scene_ready(context):
        await message.reply_text("Выберите способ задания сцены:", reply_markup=v215._scene_source_keyboard(runtime))
        return False
    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False
    refs_count = 7 if scene_mode == v215.SCENE_IMAGE else 6
    result = {"ok": False}
    async def action() -> bool:
        output: bytes | None = None
        try:
            await delivery._safe_text(message, f"⏳ Создаю изображение: {v215._shot_label(shot_mode)}, {v215._scene_mode_label(scene_mode)}. Используется {refs_count} референсов: 3 пользователя + 3 героя" + (" + фото сцены." if scene_mode == v215.SCENE_IMAGE else "."))
            output = await _comet_generate(photos, slug, scene_text, shot_mode, scene_image)
            if not output or len(output) < 1024:
                raise RuntimeError("provider returned an empty image")
            result_name = "AI-селфи" if shot_mode == v215.SHOT_SELFIE else "Совместное AI-фото"
            caption = f"🎭 {result_name} с персонажем «{meta['name']}» готово ✅\nРежим: {v215._shot_label(shot_mode)} · {v215._scene_mode_label(scene_mode)}.\nМаршрут: CometAPI / Gemini, {refs_count} референсов с равным приоритетом личности пользователя и героя. Изображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
            delivered = await delivery._deliver(message, output, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            context.user_data.pop("awaiting_ai_selfie_photo", None)
            context.user_data.pop("cs215_await_scene_image", None)
            await message.reply_text("✅ Что сделать дальше? Три фото пользователя, герой, тип кадра и текущая сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return True
        except Exception as exc:
            delivery._log_exception("V219 selfie action failed", exc)
            await delivery._safe_text(message, f"❌ Изображение не создано; средства не должны списываться. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False
    kwargs = {"remember_kind": "celebrity_selfie_v219", "remember_payload": {"character": slug, "scene": scene_text, "shot_mode": shot_mode, "scene_mode": scene_mode, "references": refs_count, "provider": "comet", "user_refs": 3, "hero_refs": 3}}
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


async def public_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    runtime = _runtime()
    query = getattr(update, "callback_query", None)
    if runtime is None or query is None:
        return
    data = str(query.data or "")
    with contextlib.suppress(Exception):
        await query.answer()
    try:
        base._activate(runtime, context, int(query.from_user.id))
        if data in {"cs201:open", "act:fun:aiselfie", "fun:aiselfie"}:
            _clear_wait_flags(context)
            await query.message.reply_text(_status_text(context), reply_markup=_main_keyboard(runtime)); return
        if data in {"cs201:photo", "act:fun:aiselfie_upload", "cs201:reuse:photos"}:
            _reset_photos(context); context.user_data["awaiting_ai_selfie_photo"] = True
            await query.message.reply_text("📸 Селфи 1/3: пришлите чёткое фото анфас без фильтров. Лицо должно быть полностью видно."); return
        if data in {"cs201:last", "act:fun:aiselfie_last"}:
            cached = base._cached_photo(runtime, int(query.from_user.id)); _reset_photos(context, cached if cached else None); context.user_data["awaiting_ai_selfie_photo"] = True
            await query.message.reply_text("✅ Последнее фото принято как селфи 1/3. Пришлите селфи 2/3 с лёгким поворотом головы." if cached else "Последнего фото нет. Пришлите селфи 1/3 анфас."); return
        if data in {"cs201:shot_menu", "cs201:reuse:shot"}:
            if len(_photos(context)) != USER_REFS:
                await query.message.reply_text(f"Сначала загрузите три фото пользователя. Получено {len(_photos(context))}/{USER_REFS}.", reply_markup=_main_keyboard(runtime))
            else:
                await query.message.reply_text("Выберите тип кадра:", reply_markup=v215._shot_keyboard(runtime))
            return
        if data.startswith("cs201:shot:"):
            mode = data.rsplit(":", 1)[-1]
            if mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON}:
                await query.message.reply_text("Выберите тип кадра:", reply_markup=v215._shot_keyboard(runtime)); return
            context.user_data["cs215_shot_mode"] = mode
            slug = str(context.user_data.get("cs201_character") or "")
            if slug and base._character_ready(runtime, slug):
                await query.message.reply_text(f"✅ Тип кадра выбран: {v215._shot_label(mode)}. Теперь выберите сцену:", reply_markup=v215._scene_source_keyboard(runtime))
            else:
                await query.message.reply_text(f"✅ Тип кадра выбран: {v215._shot_label(mode)}. Теперь выберите страну героя:", reply_markup=v208._country_kb(base, runtime))
            return
        if data in {"cs201:characters", "act:fun:aiselfie_custom", "cs201:reuse:hero"} or data.startswith("act:fun:as_preset_"):
            if len(_photos(context)) != USER_REFS:
                context.user_data["awaiting_ai_selfie_photo"] = True
                await query.message.reply_text(f"Сначала пришлите три фото пользователя. Сейчас {len(_photos(context))}/{USER_REFS}.", reply_markup=_main_keyboard(runtime))
            elif str(context.user_data.get("cs215_shot_mode") or "") not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON}:
                await query.message.reply_text("Сначала выберите тип кадра:", reply_markup=v215._shot_keyboard(runtime))
            else:
                await query.message.reply_text("⭐ Выберите страну героя:", reply_markup=v208._country_kb(base, runtime))
            return
        if data.startswith("cs201:country:"):
            country = data.rsplit(":", 1)[-1]; context.user_data["cs201_country"] = country
            await query.message.reply_text(f"⭐ {v208.COUNTRIES.get(country, ('', country))[1]}: выберите героя:", reply_markup=v208._character_kb(base, runtime, country)); return
        if data.startswith("cs201:character:"):
            slug = data.rsplit(":", 1)[-1]; meta = base.CHARACTERS.get(slug)
            if not meta:
                await query.message.reply_text("Выберите страну:", reply_markup=v208._country_kb(base, runtime))
            elif not base._character_ready(runtime, slug):
                await query.message.reply_text(f"⚠️ «{meta['name']}» пока не активирован: {base._character_status(runtime, slug)}. Загрузите 3 JPEG через /selfie_admin.")
            else:
                context.user_data["cs201_character"] = slug; context.user_data["cs201_country"] = str(meta.get("country") or "")
                await query.message.reply_text(f"✅ Герой выбран: {meta['name']}. Теперь выберите способ задания сцены:", reply_markup=v215._scene_source_keyboard(runtime))
            return
        if data in {"cs201:scene_sources", "cs201:reuse:scene"}:
            _clear_wait_flags(context); await query.message.reply_text("Выберите сцену: готовую, по описанию или по фото.", reply_markup=v215._scene_source_keyboard(runtime)); return
        if data == "cs201:scene_mode:preset":
            _clear_wait_flags(context); context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
            await query.message.reply_text("🎬 Выберите готовую сцену:", reply_markup=v215._preset_keyboard(runtime)); return
        if data == "cs201:scene_mode:description":
            _clear_wait_flags(context); context.user_data["cs215_scene_mode"] = v215.SCENE_DESCRIPTION; context.user_data["cs215_wait_scene_text"] = True
            await query.message.reply_text("📝 Опишите сцену одним сообщением: место, время суток, освещение и атмосферу."); return
        if data == "cs201:scene_mode:image":
            _clear_wait_flags(context); context.user_data["cs215_scene_mode"] = v215.SCENE_IMAGE; context.user_data["cs215_await_scene_image"] = True; context.user_data.pop("awaiting_ai_selfie_photo", None)
            await query.message.reply_text("🖼 Пришлите одно фото нужной сцены. Следующее изображение будет принято именно как референс места, а не как новое фото пользователя."); return
        if data.startswith("cs201:preset:"):
            key = data.rsplit(":", 1)[-1]; preset = base.SCENES.get(key)
            if not preset:
                await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(runtime)); return
            context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET; context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1]); context.user_data.pop("cs215_scene_image", None)
            await generate(update, context, context.user_data["cs215_scene_text"]); return
        if data in {"cs201:generate_current", "cs201:reuse:repeat"}:
            if not _scene_ready(context):
                await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(runtime))
            else:
                await generate(update, context, str(context.user_data.get("cs215_scene_text") or ""))
            return
        await v215.public_callback(update, context)
    finally:
        raise ApplicationHandlerStop


async def public_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    runtime = _runtime(); user = getattr(update, "effective_user", None); message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, int(user.id)):
        return
    if any(context.user_data.get(key) for key in ("cs212_admin_upload", "ss205_admin_upload", "cs202_admin_upload", "cs201_admin_upload")):
        from neyrobot_prod import selfie_v216_admin_upload_priority as v216
        await v216.media_router(update, context); raise ApplicationHandlerStop
    raw, url = await base._download_photo_message(message)
    if not raw:
        return
    if context.user_data.get("cs215_await_scene_image"):
        context.user_data["cs215_scene_image"] = v215._compact_scene(raw); context.user_data["cs215_scene_mode"] = v215.SCENE_IMAGE
        context.user_data["cs215_scene_text"] = "inside the uploaded real location, preserving its exact visual environment"; context.user_data["cs215_scene_label"] = "🖼 Загруженная сцена"
        context.user_data.pop("cs215_await_scene_image", None); context.user_data.pop("awaiting_ai_selfie_photo", None)
        await message.reply_text("✅ Фото сцены принято как отдельный структурный референс. Нажмите «Создать изображение».", reply_markup=v215._ready_scene_keyboard(runtime)); raise ApplicationHandlerStop
    photos = _photos(context)
    if not context.user_data.get("awaiting_ai_selfie_photo") and not (0 < len(photos) < USER_REFS):
        return
    base._activate(runtime, context, int(user.id)); count = _append_photo(context, raw)
    with contextlib.suppress(Exception):
        base._cache_photo(runtime, int(user.id), raw, url)
    if count == 1:
        context.user_data["awaiting_ai_selfie_photo"] = True; await message.reply_text("✅ Селфи 1/3 принято. Пришлите селфи 2/3 с лёгким поворотом головы на 15–30°.")
    elif count == 2:
        context.user_data["awaiting_ai_selfie_photo"] = True; await message.reply_text("✅ Селфи 2/3 принято. Пришлите селфи 3/3: ещё один естественный ракурс при хорошем освещении.")
    else:
        context.user_data.pop("awaiting_ai_selfie_photo", None); await message.reply_text("✅ Все 3/3 фото пользователя приняты. Теперь выберите тип кадра:", reply_markup=v215._shot_keyboard(runtime))
    raise ApplicationHandlerStop


async def public_text(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    runtime = _runtime(); user = getattr(update, "effective_user", None); message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, int(user.id)):
        return
    text = str(getattr(message, "text", "") or "").strip()
    if not text:
        return
    if context.user_data.get("cs215_wait_scene_text") or context.user_data.get("cs201_wait_custom_scene"):
        context.user_data.pop("cs215_wait_scene_text", None); context.user_data.pop("cs201_wait_custom_scene", None)
        context.user_data["cs215_scene_mode"] = v215.SCENE_DESCRIPTION; context.user_data["cs215_scene_text"] = text[:1600]; context.user_data.pop("cs215_scene_image", None)
        await message.reply_text("✅ Описание сцены сохранено. Нажмите «Создать изображение».", reply_markup=v215._ready_scene_keyboard(runtime)); raise ApplicationHandlerStop


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v217_user_triref as v217
    base._main_kb = _main_keyboard; base.callback = public_callback; base.media_entry = public_media; base._generate = generate
    v208._public_callback = public_callback; v208._public_media = public_media; v208._public_text = public_text; v208._generate = generate
    v215._main_keyboard = _main_keyboard; v215.generate = generate; v215._comet_generate = _comet_generate
    v217.public_callback = public_callback; v217.public_media = public_media; v217.generate = generate
    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION; runtime.AI_SELFIE_RUNTIME_VERSION = VERSION; runtime.SELFIE_STORAGE_VERSION = VERSION; runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v219-comet-3-user-3-hero-optional-scene"; runtime.AI_SELFIE_USER_REFERENCES = 3; runtime.AI_SELFIE_HERO_REFERENCES = 3
    return True


def _is_app(value: Any) -> bool:
    return value is not None and callable(getattr(value, "add_handler", None)) and isinstance(getattr(value, "handlers", None), dict)


def bind_application(app: Any) -> bool:
    if not _is_app(app) or getattr(app, _HANDLER_FLAG, False):
        return bool(_is_app(app))
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters
    app.add_handler(CallbackQueryHandler(public_callback, pattern=r"^(?:cs201:|act:fun:aiselfie(?:_upload|_last|_custom)?$|act:fun:as_preset_|fun:aiselfie$)"), group=-5000)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, public_media), group=-4999)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, public_text), group=-4998)
    setattr(app, _HANDLER_FLAG, True)
    return True


def bind_runtime_apps() -> int:
    mod = _runtime()
    if mod is None:
        return 0
    count = 0; seen: set[int] = set()
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
        app = original(self, *args, **kwargs); patch_runtime(); bind_application(app); return app
    ApplicationBuilder.build = build; setattr(ApplicationBuilder, _BUILDER_FLAG, True); return True


def install_async() -> None:
    global _STARTED
    install_builder_hook(); patch_runtime(); bind_runtime_apps()
    if _STARTED:
        return
    _STARTED = True
    def worker() -> None:
        for _ in range(21600):
            with contextlib.suppress(Exception):
                patch_runtime(); bind_runtime_apps()
            time.sleep(0.1)
    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v219-owner").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "public_callback", "public_media", "public_text", "generate", "patch_runtime", "bind_application", "install_async", "install"]
