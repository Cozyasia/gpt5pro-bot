# -*- coding: utf-8 -*-
"""V215 production workflow for Celebrity Selfie.

Adds two explicit shot modes, two custom-scene modes, uploaded-scene references,
post-result reuse controls, and an expanded Russian/American hero catalogue.

Shot modes:
* selfie: front-camera point of view; the camera/phone is not visible;
* third_person: a normal joint photograph taken by another person; no phone.

Scene sources:
* preset scene;
* custom scene described by text;
* custom scene uploaded as an image and used as an additional structural reference.

The provider route keeps V213's user identity lock (two originals + two face
crops), V211's reliable Telegram delivery, and V210's duplicate-click guard.
"""
from __future__ import annotations

import contextlib
import os
import sys
from io import BytesIO
from typing import Any

VERSION = "v215-selfie-shot-scene-production-2026-07-26"

SHOT_SELFIE = "selfie"
SHOT_THIRD_PERSON = "third_person"
SCENE_PRESET = "preset"
SCENE_DESCRIPTION = "description"
SCENE_IMAGE = "image"

NEW_CHARACTERS: dict[str, dict[str, Any]] = {
    "maria_aleksandrova": {
        "name": "Мария Александрова",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("мария александрова", "maria aleksandrova", "maria alexandrova"),
    },
    "lyubov_aksenova": {
        "name": "Любовь Аксёнова",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("любовь аксёнова", "любовь аксенова", "lyubov aksenova"),
    },
    "alexander_petrov": {
        "name": "Александр Петров",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("александр петров", "саша петров", "alexander petrov"),
    },
    "sergey_burunov": {
        "name": "Сергей Бурунов",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("сергей бурунов", "бурунов", "sergey burunov"),
    },
    "dmitry_nagiyev": {
        "name": "Дмитрий Нагиев",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("дмитрий нагиев", "нагиев", "dmitry nagiyev", "dmitry nagiev"),
    },
    "eduard_bill": {
        "name": "Эдвард Билл",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("эдвард билл", "эдвард бил", "Edward Bil", "Edward Bill"),
    },
    "mikhail_litvin": {
        "name": "Михаил Литвин",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("михаил литвин", "литвин", "mikhail litvin"),
    },
    "garik_kharlamov": {
        "name": "Гарик Харламов",
        "country": "ru",
        "required_refs": 3,
        "aliases": ("гарик харламов", "харламов", "garik kharlamov"),
    },
    "johnny_depp": {
        "name": "Джонни Депп",
        "country": "us",
        "required_refs": 3,
        "aliases": ("джонни депп", "джон депп", "johnny depp", "john depp"),
    },
    "al_pacino": {
        "name": "Аль Пачино",
        "country": "us",
        "required_refs": 3,
        "aliases": ("аль пачино", "альпачино", "al pacino"),
    },
    "robert_de_niro": {
        "name": "Роберт Де Ниро",
        "country": "us",
        "required_refs": 3,
        "aliases": ("роберт де ниро", "де ниро", "robert de niro", "robert deniro"),
    },
}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _log(label: str, exc: BaseException) -> None:
    runtime = _runtime_module()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.exception("%s: %s", label, exc)
            return
    print(f"[neyrobot-prod] {label}: {type(exc).__name__}: {exc}")


def _shot_label(mode: str) -> str:
    return "🤳 Селфи" if mode == SHOT_SELFIE else "📷 Фото от третьего лица"


def _scene_mode_label(mode: str) -> str:
    return {
        SCENE_PRESET: "🎬 Готовая сцена",
        SCENE_DESCRIPTION: "📝 Своя сцена по описанию",
        SCENE_IMAGE: "🖼 Своя сцена по фото",
    }.get(mode, "—")


def _compact_scene(raw: bytes) -> bytes:
    """Keep an uploaded room/venue reference sharp without retaining huge files."""
    data = bytes(raw or b"")
    if len(data) < 1024:
        raise ValueError("empty scene image")
    try:
        from PIL import Image, ImageOps

        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
        if max(image.size) > 1800:
            image.thumbnail((1800, 1800), Image.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=93, optimize=True, progressive=True)
        encoded = output.getvalue()
        return encoded if len(encoded) > 1024 else data
    except Exception:
        return data


def _clean_preset_scene(text: str) -> str:
    value = str(text or "").strip()
    for phrase in ("natural smartphone selfie", "smartphone selfie", "natural selfie"):
        value = value.replace(phrase, "natural realistic photography")
    return value or "a natural premium environment"


def _main_keyboard(runtime: Any):
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("📸 Загрузить 2 фото пользователя", callback_data="cs201:photo")],
        [runtime.InlineKeyboardButton("✅ Последнее фото + добавить второе", callback_data="cs201:last")],
        [runtime.InlineKeyboardButton("🤳 / 📷 Выбрать тип кадра", callback_data="cs201:shot_menu")],
        [runtime.InlineKeyboardButton("⭐ Выбрать героя", callback_data="cs201:characters")],
        [runtime.InlineKeyboardButton("⬅️ Назад в Развлечения", callback_data="mode:fun")],
    ])


def _shot_keyboard(runtime: Any):
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("🤳 Селфи — камера телефона не видна", callback_data="cs201:shot:selfie")],
        [runtime.InlineKeyboardButton("📷 Фото от третьего лица — без телефона", callback_data="cs201:shot:third_person")],
        [runtime.InlineKeyboardButton("⬅️ В меню AI-селфи", callback_data="cs201:open")],
    ])


def _scene_source_keyboard(runtime: Any):
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("🎬 Готовая сцена", callback_data="cs201:scene_mode:preset")],
        [runtime.InlineKeyboardButton("📝 Своя сцена по описанию", callback_data="cs201:scene_mode:description")],
        [runtime.InlineKeyboardButton("🖼 Своя сцена по фото", callback_data="cs201:scene_mode:image")],
        [runtime.InlineKeyboardButton("⬅️ Выбрать другого героя", callback_data="cs201:characters")],
    ])


def _preset_keyboard(runtime: Any):
    from neyrobot_prod import celebrity_selfie as base

    rows = [[runtime.InlineKeyboardButton(label, callback_data=f"cs201:preset:{key}")]
            for key, (label, _prompt) in base.SCENES.items()]
    rows.append([runtime.InlineKeyboardButton("⬅️ К способам выбора сцены", callback_data="cs201:scene_sources")])
    return runtime.InlineKeyboardMarkup(rows)


def _ready_scene_keyboard(runtime: Any):
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("✨ Создать изображение", callback_data="cs201:generate_current")],
        [runtime.InlineKeyboardButton("🔄 Выбрать другую сцену", callback_data="cs201:scene_sources")],
    ])


def _continuation_keyboard(runtime: Any, slug: str):
    from neyrobot_prod import celebrity_selfie as base

    hero_name = str((base.CHARACTERS.get(slug) or {}).get("name") or "текущий герой")
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("♻️ Повторить с текущей сценой", callback_data="cs201:reuse:repeat")],
        [runtime.InlineKeyboardButton(f"🎬 Другая сцена · {hero_name}", callback_data="cs201:reuse:scene")],
        [runtime.InlineKeyboardButton("⭐ Выбрать другого героя", callback_data="cs201:reuse:hero")],
        [runtime.InlineKeyboardButton("🤳 / 📷 Сменить тип кадра", callback_data="cs201:reuse:shot")],
        [runtime.InlineKeyboardButton("📸 Сменить фотографии пользователя", callback_data="cs201:reuse:photos")],
        [runtime.InlineKeyboardButton("⬅️ В меню AI-селфи", callback_data="cs201:open")],
    ])


def _status_text(context: Any) -> str:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    photos = len(v208._photos(context))
    shot = str(context.user_data.get("cs215_shot_mode") or "")
    slug = str(context.user_data.get("cs201_character") or "")
    hero = str((base.CHARACTERS.get(slug) or {}).get("name") or "не выбран")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    return (
        "🎭 AI-фото с героем\n\n"
        "Порядок: 1) два фото пользователя; 2) тип кадра; 3) герой; "
        "4) готовая сцена, своя сцена по описанию или своя сцена по фото.\n\n"
        f"Фото пользователя: {photos}/2\n"
        f"Тип кадра: {_shot_label(shot) if shot else 'не выбран'}\n"
        f"Герой: {hero}\n"
        f"Сцена: {_scene_mode_label(scene_mode)}"
    )


def _clear_wait_flags(context: Any) -> None:
    for key in ("cs201_wait_custom_scene", "cs215_wait_scene_text", "cs215_await_scene_image",
                "awaiting_ai_selfie_prompt", "ai_selfie_preset_prompt"):
        context.user_data.pop(key, None)


def _reset_user_photos(context: Any) -> None:
    from neyrobot_prod import selfie_v208_overlay as v208

    v208._reset_photos(context)
    context.user_data["awaiting_ai_selfie_photo"] = True


def _current_scene(context: Any) -> str:
    return str(context.user_data.get("cs215_scene_text") or "").strip()


def _scene_ready(context: Any) -> bool:
    mode = str(context.user_data.get("cs215_scene_mode") or "")
    if mode in {SCENE_PRESET, SCENE_DESCRIPTION}:
        return bool(_current_scene(context))
    if mode == SCENE_IMAGE:
        return len(bytes(context.user_data.get("cs215_scene_image") or b"")) > 1024
    return False


def _identity_and_shot_prompt(name: str, scene: str, aspect: str, shot_mode: str, has_scene_image: bool) -> str:
    if shot_mode == SHOT_THIRD_PERSON:
        shot_instructions = (
            "SHOT MODE: THIRD-PERSON JOINT PHOTO. The user and the public figure are being photographed by another person. "
            "This is not a selfie. Do not show a smartphone, selfie stick, mirror reflection, camera interface, oversized foreground hand, "
            "or any recording device in the frame. Use a natural documentary or event-photography composition."
        )
    else:
        shot_instructions = (
            "SHOT MODE: FRONT-CAMERA SELFIE POV. The final image is the photograph captured by the phone's front camera itself, "
            "not an external photograph of people holding a phone. The phone/camera must remain outside the image and must not be visible. "
            "Do not place a large smartphone, selfie stick, mirror, camera interface or device in the foreground. "
            "Both faces must be clear, unobstructed and naturally framed at selfie distance."
        )
    scene_instructions = f"SCENE REQUEST: {scene}. " if scene else "SCENE REQUEST: a natural premium real-world environment. "
    if has_scene_image:
        scene_instructions += (
            "REFERENCE 8 is the user's uploaded location/room/venue and is the authoritative scene reference. "
            "Preserve its architecture, layout, furniture, stage elements, perspective, lighting direction and atmosphere. "
            "Ignore or remove any people already visible in that scene reference and place only PERSON A and PERSON B naturally into the location. "
            "Do not copy faces or identities from the scene reference. "
        )
    return (
        "Create one photorealistic vertical image with exactly two principal people. "
        f"Aspect ratio {aspect}. {shot_instructions} {scene_instructions}"
        "IDENTITY PRESERVATION IS THE HIGHEST PRIORITY; styling and scenery are secondary. "
        "PERSON A IS THE USER. REFERENCES 1 and 3 are two original photos of the SAME USER and define body proportions, build, "
        "apparent age, skin tone, hairstyle, hairline and overall appearance. REFERENCES 2 and 4 are tight face crops of that SAME USER "
        "and are the authoritative identity anchors. The output face of PERSON A must retain the same facial geometry, eye shape and spacing, "
        "eyebrows, nose, mouth, cheeks, jawline, chin, skin tone, age and natural asymmetry visible in REFERENCES 2 and 4. "
        "Do not beautify, slim, age-shift, gender-shift, change ethnicity, average the face, or replace it with a generic model face. "
        f"PERSON B IS {name}. REFERENCES 5, 6 and 7 are three photos of that SAME second person and define PERSON B's identity. "
        "Keep PERSON A and PERSON B as two separate recognizable identities. Never merge, swap, average, duplicate or substitute faces. "
        "Preserve realistic body size and proportions from REFERENCES 1 and 3. Use natural lighting, realistic skin texture and correct anatomy. "
        "No text, logos, watermark or user-interface elements. The result is fictional AI-generated fan content and does not document a real meeting or endorsement."
    )


async def _comet_generate(user_images: list[bytes], slug: str, scene: str, shot_mode: str,
                          scene_image: bytes | None) -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen
    from neyrobot_prod import selfie_v213_user_identity_lock as identity

    runtime = _runtime_module()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    refs = base._reference_paths(runtime, slug)
    if len(user_images) != 2 or len(refs) != 3:
        raise RuntimeError(f"user photos={len(user_images)}/2, character refs={len(refs)}/3")
    prepared = [
        identity._prepare_original(base, runtime, user_images[0]),
        identity._prepare_face(base, runtime, user_images[0]),
        identity._prepare_original(base, runtime, user_images[1]),
        identity._prepare_face(base, runtime, user_images[1]),
    ]
    prepared.extend(identity._prepare_original(base, runtime, path.read_bytes()) for path in refs)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    if has_scene_image:
        prepared.append(identity._prepare_original(base, runtime, bytes(scene_image or b"")))
    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    prompt = _identity_and_shot_prompt(name, str(scene or ""), base._aspect_ratio(), shot_mode, has_scene_image)
    labels = [
        "REFERENCE 1 — USER ORIGINAL A: BODY, HAIR, AGE AND APPEARANCE",
        "REFERENCE 2 — USER FACE CROP A: PRIMARY USER IDENTITY",
        "REFERENCE 3 — USER ORIGINAL B: BODY, HAIR, AGE AND APPEARANCE",
        "REFERENCE 4 — USER FACE CROP B: PRIMARY USER IDENTITY",
        f"REFERENCE 5 — {name} PORTRAIT A",
        f"REFERENCE 6 — {name} PORTRAIT B",
        f"REFERENCE 7 — {name} PORTRAIT C",
    ]
    if has_scene_image:
        labels.append("REFERENCE 8 — USER-UPLOADED LOCATION: SCENE STRUCTURE ONLY, NOT IDENTITY")
    key = gen._comet_key()
    base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")
    headers = {"Authorization": f"Bearer {key}", "x-goog-api-key": key,
               "Content-Type": "application/json", "Accept": "application/json"}
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
                    parts.append({"inlineData": {"mimeType": mime, "data": data}} if camel
                                 else {"inline_data": {"mime_type": mime, "data": data}})
                config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
                if not compatibility:
                    config["imageConfig"] = {"aspectRatio": base._aspect_ratio(), "imageSize": base._image_size()}
                try:
                    response = await client.post(
                        f"{base_url}/v1beta/models/{model}:generateContent", headers=headers,
                        json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config},
                    )
                    if response.status_code >= 400:
                        errors.append(f"{model}: HTTP {response.status_code}: {response.text[:350]}")
                        continue
                    output = gen._extract_final_image(response.json())
                    if output:
                        return output
                    errors.append(f"{model}: response contained no final image")
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Comet V215 generation failed: " + " | ".join(errors[-8:]))


def _preserve_state(runtime: Any, context: Any, user_id: int, slug: str) -> None:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    photos = v208._photos(context)
    meta = base.CHARACTERS.get(slug) or {}
    with contextlib.suppress(Exception):
        base._activate(runtime, context, int(user_id))
    context.user_data["cs201_character"] = slug
    context.user_data["cs201_country"] = str(meta.get("country") or "")
    context.user_data["cs201_user_photos"] = list(photos[:2])
    context.user_data["cs201_user_photo_step"] = len(photos[:2])
    context.user_data["cs201_user_photo_ready"] = len(photos) == 2
    _clear_wait_flags(context)
    context.user_data.pop("awaiting_ai_selfie_photo", None)


async def generate(update: Any, context: Any, scene: str) -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v211_delivery as v211

    runtime = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False
    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    photos = v208._photos(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or _current_scene(context) or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == SCENE_IMAGE else None
    if not meta:
        await v211._safe_text(message, "Сначала выберите страну и героя.")
        return False
    if not base._character_ready(runtime, slug):
        await v211._safe_text(message, f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(runtime, slug)}.")
        return False
    if len(photos) != 2:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await v211._safe_text(message, "Нужны два фото пользователя. Загрузите фото 1/2 и фото 2/2 заново.")
        return False
    if shot_mode not in {SHOT_SELFIE, SHOT_THIRD_PERSON}:
        await message.reply_text("Сначала выберите тип кадра:", reply_markup=_shot_keyboard(runtime))
        return False
    if scene_mode not in {SCENE_PRESET, SCENE_DESCRIPTION, SCENE_IMAGE} or not _scene_ready(context):
        await message.reply_text("Выберите способ задания сцены:", reply_markup=_scene_source_keyboard(runtime))
        return False
    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await v211._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False
    refs_count = 8 if scene_mode == SCENE_IMAGE else 7
    result = {"ok": False}

    async def action() -> bool:
        output: bytes | None = None
        try:
            await v211._safe_text(
                message,
                f"⏳ Создаю изображение: {_shot_label(shot_mode)}, {_scene_mode_label(scene_mode)}. "
                f"Используется {refs_count} референсов. Обычно это занимает 1–3 минуты.",
            )
            output = await _comet_generate(photos, slug, scene_text, shot_mode, scene_image)
            if not output or len(output) < 1024:
                raise RuntimeError("provider returned an empty image")
            result_name = "AI-селфи" if shot_mode == SHOT_SELFIE else "Совместное AI-фото"
            caption = (
                f"🎭 {result_name} с персонажем «{meta['name']}» готово ✅\n"
                f"Режим: {_shot_label(shot_mode)} · {_scene_mode_label(scene_mode)}.\n"
                f"Маршрут: CometAPI / Gemini, {refs_count} референсов с усилением личности пользователя. "
                "Изображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
            )
            prefer_document = bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True))
            delivered = await v211._deliver(message, output, caption, prefer_document=prefer_document)
            result["ok"] = bool(delivered)
            _preserve_state(runtime, context, int(user.id), slug)
            await message.reply_text(
                "✅ Что сделать дальше? Фото пользователя, герой, тип кадра и текущая сцена сохранены.",
                reply_markup=_continuation_keyboard(runtime, slug), write_timeout=90.0,
                read_timeout=90.0, connect_timeout=30.0, pool_timeout=30.0,
            )
            return True
        except Exception as exc:
            v211._log_exception("V215 selfie action failed", exc)
            recovery = (v211._save_recovery_copy(runtime, int(user.id),
                        v211._jpeg(output or b"", max_side=1800, quality=91)) if output else None)
            if recovery is not None:
                await v211._safe_text(message, "❌ Изображение было создано, но Telegram не принял файл после повторных попыток. "
                                      "Средства не должны списываться. Результат сохранён на сервере для диагностики.")
            else:
                detail = f"{type(exc).__name__}: {str(exc)[:700]}"
                await v211._safe_text(message, "❌ Изображение не создано; средства не должны списываться. "
                                      f"Техническая причина: {detail}")
            return False

    kwargs = {"remember_kind": "celebrity_selfie_v215", "remember_payload": {
        "character": slug, "scene": scene_text, "shot_mode": shot_mode, "scene_mode": scene_mode,
        "references": refs_count, "provider": "comet", "identity_lock": True, "reuse_controls": True}}
    if v211._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img",
                 max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)),
                 action, **kwargs)
    return bool(result["ok"])


async def public_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    runtime = _runtime_module()
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
            await query.message.reply_text(_status_text(context), reply_markup=_main_keyboard(runtime))
            return
        if data in {"cs201:photo", "act:fun:aiselfie_upload", "cs201:reuse:photos"}:
            _reset_user_photos(context)
            await query.message.reply_text("📸 Фото пользователя 1/2: пришлите чёткую фотографию анфас без фильтров. "
                                           "Лицо должно быть хорошо видно; можно использовать портрет или фото по пояс.")
            return
        if data in {"cs201:last", "act:fun:aiselfie_last"}:
            cached = base._cached_photo(runtime, int(query.from_user.id))
            v208._reset_photos(context, cached if cached else None)
            context.user_data["awaiting_ai_selfie_photo"] = True
            await query.message.reply_text("✅ Последнее фото принято как фото 1/2. Пришлите фото 2/2 с поворотом головы 15–30°."
                                           if cached else "Последнего фото нет. Пришлите фото пользователя 1/2 анфас.")
            return
        if data in {"cs201:shot_menu", "cs201:reuse:shot"}:
            if len(v208._photos(context)) != 2:
                _reset_user_photos(context)
                await query.message.reply_text("Сначала загрузите два фото пользователя.", reply_markup=_main_keyboard(runtime))
            else:
                await query.message.reply_text(
                    "Выберите тип кадра:\n\n"
                    "🤳 Селфи — результат выглядит как снимок с фронтальной камеры, но сам телефон в кадре не показывается.\n"
                    "📷 Фото от третьего лица — пользователя и героя фотографирует другой человек; телефона в кадре нет.",
                    reply_markup=_shot_keyboard(runtime))
            return
        if data.startswith("cs201:shot:"):
            mode = data.rsplit(":", 1)[-1]
            if mode not in {SHOT_SELFIE, SHOT_THIRD_PERSON}:
                await query.message.reply_text("Выберите тип кадра:", reply_markup=_shot_keyboard(runtime))
                return
            context.user_data["cs215_shot_mode"] = mode
            slug = str(context.user_data.get("cs201_character") or "")
            if slug and base._character_ready(runtime, slug):
                await query.message.reply_text(f"✅ Тип кадра выбран: {_shot_label(mode)}. Теперь выберите сцену:",
                                               reply_markup=_scene_source_keyboard(runtime))
            else:
                await query.message.reply_text(f"✅ Тип кадра выбран: {_shot_label(mode)}. Теперь выберите страну героя:",
                                               reply_markup=v208._country_kb(base, runtime))
            return
        if data in {"cs201:characters", "act:fun:aiselfie_custom", "cs201:reuse:hero"} or data.startswith("act:fun:as_preset_"):
            if len(v208._photos(context)) != 2:
                _reset_user_photos(context)
                await query.message.reply_text("Сначала пришлите два фото пользователя.", reply_markup=_main_keyboard(runtime))
            elif str(context.user_data.get("cs215_shot_mode") or "") not in {SHOT_SELFIE, SHOT_THIRD_PERSON}:
                await query.message.reply_text("Сначала выберите тип кадра:", reply_markup=_shot_keyboard(runtime))
            else:
                await query.message.reply_text("⭐ Выберите страну героя:", reply_markup=v208._country_kb(base, runtime))
            return
        if data.startswith("cs201:country:"):
            country = data.rsplit(":", 1)[-1]
            if country not in v208.COUNTRIES:
                await query.message.reply_text("Выберите страну:", reply_markup=v208._country_kb(base, runtime))
            else:
                context.user_data["cs201_country"] = country
                await query.message.reply_text(f"⭐ {v208.COUNTRIES[country][1]}: выберите героя:",
                                               reply_markup=v208._character_kb(base, runtime, country))
            return
        if data.startswith("cs201:character:"):
            slug = data.rsplit(":", 1)[-1]
            meta = base.CHARACTERS.get(slug)
            if not meta:
                await query.message.reply_text("Выберите страну:", reply_markup=v208._country_kb(base, runtime))
            elif not base._character_ready(runtime, slug):
                await query.message.reply_text(f"⚠️ «{meta['name']}» пока не активирован: {base._character_status(runtime, slug)}. "
                                               "Загрузите 3 JPEG через /selfie_admin.")
            else:
                context.user_data["cs201_character"] = slug
                context.user_data["cs201_country"] = str(meta.get("country") or "")
                await query.message.reply_text(f"✅ Герой выбран: {meta['name']}. Теперь выберите способ задания сцены:",
                                               reply_markup=_scene_source_keyboard(runtime))
            return
        if data in {"cs201:scene_sources", "cs201:reuse:scene"}:
            if not context.user_data.get("cs201_character"):
                await query.message.reply_text("Сначала выберите героя.", reply_markup=v208._country_kb(base, runtime))
            else:
                _clear_wait_flags(context)
                await query.message.reply_text(
                    "Выберите сцену:\n\n🎬 Готовая сцена — один из встроенных вариантов.\n"
                    "📝 По описанию — напишите место и обстановку.\n"
                    "🖼 По фото — загрузите комнату, зал, квартиру, ресторан, офис или площадку.",
                    reply_markup=_scene_source_keyboard(runtime))
            return
        if data == "cs201:scene_mode:preset":
            _clear_wait_flags(context)
            context.user_data["cs215_scene_mode"] = SCENE_PRESET
            await query.message.reply_text("🎬 Выберите готовую сцену:", reply_markup=_preset_keyboard(runtime))
            return
        if data == "cs201:scene_mode:description":
            _clear_wait_flags(context)
            context.user_data["cs215_scene_mode"] = SCENE_DESCRIPTION
            context.user_data["cs215_wait_scene_text"] = True
            await query.message.reply_text("📝 Опишите сцену одним сообщением. Укажите место, время суток, освещение и атмосферу.\n\n"
                                           "Пример: «в современной VIP-ложе футбольного стадиона вечером, мягкий свет, праздничная атмосфера».")
            return
        if data == "cs201:scene_mode:image":
            _clear_wait_flags(context)
            context.user_data["cs215_scene_mode"] = SCENE_IMAGE
            context.user_data["cs215_await_scene_image"] = True
            await query.message.reply_text(
                "🖼 Пришлите одно фото нужной сцены: комнаты, квартиры, офиса, ресторана, концертной площадки, зала или другого места.\n\n"
                "Рекомендации:\n• лучше без людей или с минимальным количеством людей;\n• без сильного размытия;\n"
                "• в кадре должно быть свободное место для двух человек;\n"
                "• хорошо видимые стены, мебель, сцена и направление света повышают точность.")
            return
        if data.startswith("cs201:preset:"):
            key = data.rsplit(":", 1)[-1]
            preset = base.SCENES.get(key)
            if not preset:
                await query.message.reply_text("Выберите готовую сцену:", reply_markup=_preset_keyboard(runtime))
                return
            context.user_data["cs215_scene_mode"] = SCENE_PRESET
            context.user_data["cs215_scene_text"] = _clean_preset_scene(preset[1])
            context.user_data["cs215_scene_label"] = preset[0]
            context.user_data.pop("cs215_scene_image", None)
            await base._generate(runtime, update, context, context.user_data["cs215_scene_text"])
            return
        if data.startswith("cs201:scene:"):
            key = data.rsplit(":", 1)[-1]
            if key == "custom":
                context.user_data["cs215_scene_mode"] = SCENE_DESCRIPTION
                context.user_data["cs215_wait_scene_text"] = True
                await query.message.reply_text("📝 Опишите сцену и обстановку одним сообщением.")
            elif key in base.SCENES:
                preset = base.SCENES[key]
                context.user_data["cs215_scene_mode"] = SCENE_PRESET
                context.user_data["cs215_scene_text"] = _clean_preset_scene(preset[1])
                context.user_data["cs215_scene_label"] = preset[0]
                context.user_data.pop("cs215_scene_image", None)
                await base._generate(runtime, update, context, context.user_data["cs215_scene_text"])
            else:
                await query.message.reply_text("Выберите сцену:", reply_markup=_scene_source_keyboard(runtime))
            return
        if data == "cs201:generate_current":
            if not _scene_ready(context):
                await query.message.reply_text("Сцена ещё не задана.", reply_markup=_scene_source_keyboard(runtime))
            else:
                await base._generate(runtime, update, context, _current_scene(context))
            return
        if data == "cs201:reuse:repeat":
            if not _scene_ready(context):
                await query.message.reply_text("Текущая сцена не сохранена. Выберите новую.", reply_markup=_scene_source_keyboard(runtime))
            else:
                await base._generate(runtime, update, context, _current_scene(context))
            return
    finally:
        raise ApplicationHandlerStop


async def public_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    if context.user_data.get("cs212_admin_upload"):
        return
    runtime = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, int(user.id)):
        return
    try:
        raw, url = await base._download_photo_message(message)
        if not raw:
            return
        if context.user_data.get("cs215_await_scene_image"):
            context.user_data["cs215_scene_image"] = _compact_scene(raw)
            context.user_data["cs215_scene_mode"] = SCENE_IMAGE
            context.user_data["cs215_scene_text"] = "inside the uploaded real location, preserving its exact visual environment"
            context.user_data["cs215_scene_label"] = "🖼 Загруженная сцена"
            context.user_data.pop("cs215_await_scene_image", None)
            await message.reply_text("✅ Фото сцены принято. Оно будет использовано как структурный референс помещения или площадки.\n"
                                     "Нажмите «Создать изображение».", reply_markup=_ready_scene_keyboard(runtime))
            return
        if not context.user_data.get("awaiting_ai_selfie_photo") and len(v208._photos(context)) >= 2:
            await message.reply_text("Два фото пользователя уже сохранены. Используйте кнопку смены фотографий или загрузки своей сцены.",
                                     reply_markup=_main_keyboard(runtime))
            return
        base._activate(runtime, context, int(user.id))
        count = v208._append_photo(context, raw)
        base._cache_photo(runtime, int(user.id), raw, url)
        if count == 1:
            context.user_data["awaiting_ai_selfie_photo"] = True
            await message.reply_text("✅ Фото 1/2 принято. Теперь пришлите фото 2/2 с лёгким поворотом головы. "
                                     "Желательно, чтобы лицо снова было хорошо видно.")
        else:
            context.user_data.pop("awaiting_ai_selfie_photo", None)
            await message.reply_text("✅ Фото 2/2 принято. Теперь выберите тип кадра:", reply_markup=_shot_keyboard(runtime))
    finally:
        raise ApplicationHandlerStop


async def public_text(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    runtime = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None or not base._active(runtime, context, int(user.id)):
        return
    text = str(getattr(message, "text", "") or "").strip()
    if not text:
        return
    try:
        if context.user_data.get("cs215_wait_scene_text") or context.user_data.get("cs201_wait_custom_scene"):
            context.user_data.pop("cs215_wait_scene_text", None)
            context.user_data.pop("cs201_wait_custom_scene", None)
            context.user_data["cs215_scene_mode"] = SCENE_DESCRIPTION
            context.user_data["cs215_scene_text"] = text[:1600]
            context.user_data["cs215_scene_label"] = "📝 Своя сцена по описанию"
            context.user_data.pop("cs215_scene_image", None)
            await message.reply_text("✅ Описание сцены сохранено. Нажмите «Создать изображение» или выберите другой способ задания сцены.",
                                     reply_markup=_ready_scene_keyboard(runtime))
            return
        await message.reply_text("Используйте кнопки AI-фото: можно сменить героя, тип кадра, фотографии пользователя или сцену.",
                                 reply_markup=_main_keyboard(runtime))
    finally:
        raise ApplicationHandlerStop


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    runtime = _runtime_module()
    try:
        if runtime is None:
            return
        ready = sum(1 for slug in base.CHARACTERS if base._character_ready(runtime, slug))
        lines = [
            "💾 Selfie Production diagnostic", f"version={VERSION}", f"storage={base._storage_root(runtime)}",
            f"data_is_mount={'on' if os.path.ismount('/data') else 'off'}", "persistent_storage=on",
            f"characters={len(base.CHARACTERS)}", f"characters_ready={ready}",
            "shot_modes=selfie,third_person", "scene_modes=preset,description,image",
            "generator=v215-comet-user-identity-shot-scene", "user_original_references=2",
            "user_face_crop_references=2", "hero_references=3", "scene_image_references=0_or_1",
            "references_per_request=7_or_8", "phone_visible_in_selfie=off", "phone_visible_in_third_person=off",
        ]
        for slug in base.CHARACTERS:
            lines.append(f"{slug}={base._character_status(runtime, slug)} ready={'on' if base._character_ready(runtime, slug) else 'off'}")
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_admin_v212_catalog as admin_v212
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v210_generation_guard as v210
    from neyrobot_prod import selfie_v211_delivery as v211
    from neyrobot_prod import selfie_v213_user_identity_lock as v213
    from neyrobot_prod import selfie_v214_reuse_controls as v214

    generator_v204.patch = lambda: True
    v208.patch = lambda: True
    v209.patch_runtime = lambda: True
    v210.patch_runtime = lambda: True
    runtime_v207.patch_runtime = lambda: True
    v208.CHARACTERS.update(NEW_CHARACTERS)
    base.CHARACTERS.update(v208.CHARACTERS)
    with contextlib.suppress(Exception):
        storage_v205.CHARACTER_ADDITIONS.update(NEW_CHARACTERS)
    runtime = _runtime_module()
    if runtime is not None:
        for slug in NEW_CHARACTERS:
            base._character_dir(runtime, slug).mkdir(parents=True, exist_ok=True)
    base._main_kb = _main_keyboard
    base.callback = public_callback
    base.media_entry = public_media
    base.text_entry = public_text
    v208._public_callback = public_callback
    v208._public_media = public_media
    v208._public_text = public_text
    v208._generate = generate
    v208._diag_storage = diagnostic
    v211.generate = generate
    v214.generate = generate
    storage_v205.diagnostic = diagnostic
    for module in (v208, v209, v210, v211, v213, v214, admin_v212, generator_v204,
                   commands_v206, runtime_v207, storage_v205):
        module.VERSION = VERSION
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v215-shot-modes-custom-scenes-7-or-8-reference"
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.SELFIE_SHOT_MODES = (SHOT_SELFIE, SHOT_THIRD_PERSON)
        runtime.SELFIE_SCENE_MODES = (SCENE_PRESET, SCENE_DESCRIPTION, SCENE_IMAGE)
        runtime.SELFIE_NEW_CHARACTERS = tuple(NEW_CHARACTERS)
    return True


def install_async() -> None:
    patch_runtime()


def install() -> None:
    install_async()


__all__ = ["VERSION", "NEW_CHARACTERS", "public_callback", "public_media", "public_text",
           "generate", "diagnostic", "patch_runtime", "install_async", "install"]
