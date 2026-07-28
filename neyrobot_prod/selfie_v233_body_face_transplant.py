# -*- coding: utf-8 -*-
"""V233 body-first Celebrity Selfie pipeline.

The current stable V232 state is preserved on branch
backup/v232-2026-07-29-before-v233.

Flow:
1. User supplies three face portraits plus one full-body photo.
2. Pass 1 builds the scene, hero, pose, clothing and user body proportions.
3. Pass 2 performs a localized user head/face identity transplant.
4. Pass 3 performs a conservative identity QC repair while pixel-locking the rest.

Only the official Google Gemini Developer API and GEMINI_IMAGE_API_KEY are used.
Legacy Comet generation is disabled for this mode.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sys
import threading
import time
from typing import Any

VERSION = "v233-selfie-body-face-transplant-google-2026-07-29"
_HANDLER_FLAG = "_selfie_v233_body_face_handler_bound"
_MEDIA_FLAG = "_selfie_v233_full_body_media_bound"
_STARTED = False
_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$|cs233:full_body$)"
_FULL_BODY_KEY = "cs233_user_full_body"
_AWAIT_FULL_BODY = "cs233_await_full_body"
_ORIGINAL_MAIN_KEYBOARD = None


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _key() -> str:
    return (os.environ.get("GEMINI_IMAGE_API_KEY") or "").strip()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else "missing"


def _models() -> list[str]:
    raw = (os.environ.get("GEMINI_SELFIE_MODELS") or "gemini-3-pro-image,gemini-3.1-flash-image").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def _base_url() -> str:
    return (os.environ.get("GEMINI_API_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")


def _log(message: str, *args: Any) -> None:
    runtime = _runtime()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.info(message, *args)
            return
    print(message % args if args else message, flush=True)


def _prepare(raw: bytes) -> tuple[str, str]:
    from neyrobot_prod import celebrity_selfie as base
    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    return base._prepare_image(runtime, bytes(raw or b""))


def _inline(data: str, mime: str) -> dict[str, Any]:
    return {"inlineData": {"mimeType": mime, "data": data}}


async def _call_google(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    import httpx
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as extractor

    key = _key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

    prepared = [(label, *_prepare(raw)) for label, raw in labeled_images]
    timeout_s = max(300.0, float(os.environ.get("GEMINI_SELFIE_TIMEOUT_S", "420") or 420))
    timeout = httpx.Timeout(timeout_s, connect=45.0, read=timeout_s, write=210.0, pool=45.0)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    errors: list[str] = []

    _log(
        "AI_SELFIE_V233_STAGE_START stage=%s provider=Google-Gemini-direct key_fp=%s models=%s refs=%s",
        stage, _fingerprint(key), ",".join(_models()), len(labeled_images),
    )

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for model in _models():
            for compatibility in (False, True):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, data, mime in prepared:
                    parts.append({"text": label})
                    parts.append(_inline(data, mime))
                config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
                if not compatibility:
                    config["imageConfig"] = {
                        "aspectRatio": base._aspect_ratio(),
                        "imageSize": os.environ.get("GEMINI_SELFIE_IMAGE_SIZE", "2K"),
                    }
                try:
                    response = await client.post(
                        f"{_base_url()}/models/{model}:generateContent",
                        headers=headers,
                        json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config},
                    )
                    if response.status_code >= 400:
                        errors.append(f"{stage}/{model}: HTTP {response.status_code}: {response.text[:500]}")
                        continue
                    output = extractor._extract_final_image(response.json())
                    if output and len(output) > 1024:
                        runtime = _runtime()
                        if runtime is not None:
                            runtime.AI_SELFIE_LAST_PROVIDER = "google_gemini_direct"
                            runtime.AI_SELFIE_LAST_MODEL = model
                            runtime.AI_SELFIE_LAST_STAGE = stage
                        _log(
                            "AI_SELFIE_V233_STAGE_SUCCESS stage=%s model=%s refs=%s bytes=%s key_fp=%s",
                            stage, model, len(labeled_images), len(output), _fingerprint(key),
                        )
                        return output, model
                    errors.append(f"{stage}/{model}: response contained no final image")
                except Exception as exc:
                    errors.append(f"{stage}/{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Direct Google Gemini failed: " + " | ".join(errors[-8:]))


def _full_body(context: Any) -> bytes | None:
    raw = bytes(context.user_data.get(_FULL_BODY_KEY) or b"")
    return raw if len(raw) > 1024 else None


def _face_and_hero_refs(user_images: list[bytes], slug: str) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v213_user_identity_lock as identity
    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    hero_paths = base._reference_paths(runtime, slug)
    if len(user_images) != 3 or len(hero_paths) != 3:
        raise RuntimeError(f"user face photos={len(user_images)}/3, hero refs={len(hero_paths)}/3")
    user_refs: list[tuple[str, bytes]] = []
    for idx, raw in enumerate(user_images, 1):
        user_refs.append((f"USER FACE ORIGINAL {idx}: authoritative identity and age", bytes(raw)))
        user_refs.append((f"USER FACE CROP {idx}: highest-priority craniofacial identity", identity._user_face_crop(bytes(raw))))
    hero_refs = [(f"HERO PORTRAIT {idx}: authoritative PERSON B identity", path.read_bytes()) for idx, path in enumerate(hero_paths, 1)]
    return user_refs, hero_refs


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool) -> str:
    scene_rule = (
        "The first reference is the authoritative location. Preserve its architecture, furniture, camera viewpoint, crop, perspective and lighting. "
        if has_scene_image else f"Create the requested scene faithfully: {scene}. "
    )
    return (
        "COMPOSITION AND BODY PASS. Create one photorealistic vertical image with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}"
        "PERSON A is the user. The labeled FULL-BODY reference is authoritative for PERSON A's height impression, shoulder width, torso volume, waist, arms, legs, posture, body proportions, clothing fit and overall build. "
        "Do not slim, enlarge, athleticize or redesign PERSON A's body. Preserve the clothing category and realistic fit from the full-body reference unless the scene requires only a minimal practical adaptation. "
        "The three user portraits define approximate face, hair, age and skin tone for placement, but this pass prioritizes body, pose, scene and natural integration. Keep PERSON A's face clear, unobstructed and near-frontal or mild three-quarter so it can be repaired later. "
        f"PERSON B is {name}; the three hero portraits are authoritative. Maximize PERSON B identity fidelity. Keep identities separate. "
        "Use realistic anatomy, optics, skin texture and lighting. No text, watermark or interface."
    )


def _stage2_prompt(name: str) -> str:
    return (
        "LOCALIZED USER FACE TRANSPLANT PASS. The first image is the authoritative completed composition. Return the same photograph and alter ONLY PERSON A's head/face/hairline/ears as needed to match the user identity references. "
        "Pixel-lock PERSON B, both bodies below the neck, pose, hands, clothing, accessories, furniture, architecture, background, camera, crop, perspective, lighting, shadows and colors. "
        "The FULL-BODY reference protects PERSON A's body proportions and clothing. The six portrait references are authoritative for PERSON A's identity. Reconstruct the complete natural head, not a pasted mask: skull width and height, forehead, hairline, temples, ears, eye shape and spacing, brows, nose, philtrum, lips, cheeks, jaw, chin, skin tone, age and asymmetry. "
        "Blend skin texture and illumination naturally into the base image. Do not beautify, slim the face, sharpen the jaw, rejuvenate or substitute a generic similar person. "
        f"PERSON B is {name}; do not alter PERSON B. Output one photorealistic image only."
    )


def _stage3_prompt(name: str) -> str:
    return (
        "STRICT IDENTITY QC REPAIR. The first image is the accepted composition after face transplant. Preserve it exactly except for tiny corrections inside PERSON A's head region. "
        "Compare PERSON A against all six portrait anchors. Correct residual mismatch in head width, cheeks, eye spacing, eyelids, nose, mouth, jaw, chin, ears, hairline, apparent age and natural asymmetry. Preserve the user's real fuller facial proportions. "
        "Do not modify neck, body, clothing, pose, hands, scene, crop, lighting or PERSON B. Do not create a new composition. "
        f"PERSON B is {name} and is fully locked. Output one photorealistic image only."
    )


def _body_button(runtime: Any):
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton("🧍 Загрузить фото в полный рост", callback_data="cs233:full_body")],
        [runtime.InlineKeyboardButton("⬅️ Назад в AI-селфи", callback_data="cs201:open")],
    ])


def _patched_main_keyboard(runtime: Any):
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    global _ORIGINAL_MAIN_KEYBOARD
    original = _ORIGINAL_MAIN_KEYBOARD
    if original is None:
        original = getattr(v219, "_main_keyboard")
    markup = original(runtime)
    rows = list(getattr(markup, "inline_keyboard", []) or [])
    if not any(any(getattr(button, "callback_data", "") == "cs233:full_body" for button in row) for row in rows):
        rows.insert(1, [runtime.InlineKeyboardButton("🧍 Загрузить фото в полный рост", callback_data="cs233:full_body")])
    return runtime.InlineKeyboardMarkup(rows)


async def full_body_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    message = getattr(update, "effective_message", None)
    if message is None or not context.user_data.get(_AWAIT_FULL_BODY):
        return
    raw, _url = await base._download_photo_message(message)
    if not raw:
        return
    context.user_data[_FULL_BODY_KEY] = bytes(raw)
    context.user_data.pop(_AWAIT_FULL_BODY, None)
    await message.reply_text(
        "✅ Фото в полный рост принято. Оно будет использоваться только для комплекции, пропорций тела, одежды и позы. Теперь выберите героя, тип кадра и сцену.",
        reply_markup=_patched_main_keyboard(_runtime()),
    )
    raise ApplicationHandlerStop


async def callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")
    with contextlib.suppress(Exception):
        await query.answer()

    if data == "cs233:full_body":
        context.user_data[_AWAIT_FULL_BODY] = True
        context.user_data.pop("cs215_await_scene_image", None)
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        await query.message.reply_text(
            "🧍 Пришлите одно чёткое фото в полный рост. Всё тело должно быть видно, без зеркального широкоугольного искажения, в обычной одежде и при хорошем освещении."
        )
        raise ApplicationHandlerStop

    if data.startswith("cs201:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if preset:
            context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
            context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
            context.user_data.pop("cs215_scene_image", None)
            await generate(update, context, context.user_data["cs215_scene_text"])
        else:
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(_runtime()))
        raise ApplicationHandlerStop

    if data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if v219._scene_ready(context):
            await generate(update, context, str(context.user_data.get("cs215_scene_text") or ""))
        else:
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(_runtime()))
        raise ApplicationHandlerStop


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    runtime = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    faces = v219._photos(context)
    full_body = _full_body(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or context.user_data.get("cs215_scene_text") or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == v215.SCENE_IMAGE else None

    if not meta or len(faces) != 3 or shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON} or not v219._scene_ready(context):
        await delivery._safe_text(message, "❌ Не хватает данных: нужны 3 портрета пользователя, фото в полный рост, герой, тип кадра и сцена.")
        return False
    if not full_body:
        await message.reply_text(
            "🧍 Для нового точного режима нужно отдельное фото пользователя в полный рост.",
            reply_markup=_body_button(runtime),
        )
        return False
    if not _key():
        await delivery._safe_text(message, "❌ Отсутствует GEMINI_IMAGE_API_KEY. CometAPI и альтернативные ключи отключены.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    face_refs, hero_refs = _face_and_hero_refs(faces, slug)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE", bytes(scene_image)))
    stage1_refs.append(("USER FULL-BODY: authoritative body proportions, build, posture and clothing", full_body))
    stage1_refs.extend([(f"USER PORTRAIT {idx}: approximate placement identity", raw) for idx, raw in enumerate(faces, 1)])
    stage1_refs.extend(hero_refs)

    result = {"ok": False}

    async def action() -> bool:
        try:
            await delivery._safe_text(message, f"⏳ Этап 1/3: создаю сцену, героя, тело и одежду пользователя. Референсов: {len(stage1_refs)}.")
            stage1, model1 = await _call_google(
                _stage1_prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "scene_body_composition",
            )

            await delivery._safe_text(message, "🧬 Этап 2/3: локально переношу точную личность пользователя на готовую голову, не меняя тело, одежду, героя и сцену.")
            stage2_refs = [("AUTHORITATIVE COMPLETED BASE", stage1), ("USER FULL-BODY: lock body and clothing", full_body)] + face_refs + hero_refs
            stage2, model2 = await _call_google(_stage2_prompt(str(meta["name"])), stage2_refs, "localized_face_transplant")

            await delivery._safe_text(message, "🔎 Этап 3/3: выполняю строгую проверку и минимальную коррекцию сходства пользователя.")
            stage3_refs = [("AUTHORITATIVE TRANSPLANTED BASE", stage2)] + face_refs + hero_refs
            final, model3 = await _call_google(_stage3_prompt(str(meta["name"])), stage3_refs, "identity_qc_repair")

            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                f"Маршрут: прямой Google Gemini API · 3 этапа · модели: {model1} → {model2} → {model3}.\n"
                "Тело и одежда: отдельное фото в полный рост. Личность: 3 портрета + 3 кропа лица. CometAPI не используется. "
                "Изображение создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Данные пользователя, фото в полный рост, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V233 body-face transplant failed", exc)
            await delivery._safe_text(message, f"❌ Трёхэтапный Google Gemini не создал изображение. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v233_body_face_transplant",
        "remember_payload": {
            "character": slug,
            "provider": "google_gemini_direct",
            "stages": 3,
            "user_face_originals": 3,
            "user_face_crops": 3,
            "user_full_body": True,
            "hero_refs": 3,
            "scene_image": has_scene_image,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    cost = max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20))
    await runner(update, context, int(user.id), "img", cost, action, **kwargs)
    return bool(result["ok"])


def _is_legacy_generation_handler(handler: Any) -> bool:
    callback_fn = getattr(handler, "callback", None)
    if callback_fn is callback:
        return False
    module = str(getattr(callback_fn, "__module__", ""))
    pattern = str(getattr(handler, "pattern", "") or "")
    return module.startswith("neyrobot_prod.selfie_") and any(token in pattern for token in ("cs201:preset", "generate_current", "reuse:repeat"))


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)) or not isinstance(getattr(app, "handlers", None), dict):
        return False
    for group, handlers in list(app.handlers.items()):
        app.handlers[group] = [handler for handler in handlers if not _is_legacy_generation_handler(handler)]
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters
    if not getattr(app, _HANDLER_FLAG, False):
        app.add_handler(CallbackQueryHandler(callback, pattern=_GENERATION_PATTERN), group=-30000)
        setattr(app, _HANDLER_FLAG, True)
    if not getattr(app, _MEDIA_FLAG, False):
        app.add_handler(MessageHandler(filters.PHOTO, full_body_media), group=-30000)
        setattr(app, _MEDIA_FLAG, True)
    return True


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    global _ORIGINAL_MAIN_KEYBOARD
    if _ORIGINAL_MAIN_KEYBOARD is None and getattr(v219, "_main_keyboard", None) is not _patched_main_keyboard:
        _ORIGINAL_MAIN_KEYBOARD = v219._main_keyboard

    base._generate = generate
    v208._generate = generate
    v215.generate = generate
    v217.generate = generate
    v219.generate = generate
    v219.public_callback.__globals__["generate"] = generate
    v219._main_keyboard = _patched_main_keyboard

    async def _disabled_comet(*args: Any, **kwargs: Any):
        raise RuntimeError("Legacy Comet selfie route is disabled by V233")
    v219._comet_generate = _disabled_comet

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v233-body-first-local-face-transplant-google-three-stage"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_ACTIVE_KEY_FINGERPRINT = _fingerprint(_key())
        runtime.AI_SELFIE_GENERATION_STAGES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_CROPS = 3
        runtime.AI_SELFIE_USER_FULL_BODY_REFERENCES = 1
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        for value in list(vars(runtime).values()):
            with contextlib.suppress(Exception):
                bind_application(value)
    return True


def install_async() -> None:
    global _STARTED
    with contextlib.suppress(Exception):
        patch_runtime()
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        while True:
            try:
                patch_runtime()
            except Exception as exc:
                _log("V233 canonical owner patch failed: %r", exc)
            time.sleep(0.10)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v233-body-face-transplant").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "generate", "callback", "full_body_media", "bind_application", "patch_runtime", "install_async", "install"]
