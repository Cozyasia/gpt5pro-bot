# -*- coding: utf-8 -*-
"""V229 canonical Celebrity Selfie pipeline.

This module removes legacy generation callback handlers and installs one canonical
handler for preset/current/repeat generation. Both passes use the official Google
Gemini Developer API and only GEMINI_IMAGE_API_KEY.

Pass 1 creates the composition from 3 user originals, 3 user face crops, 3 hero
references and an optional uploaded scene image. Pass 2 receives the generated
image as an authoritative base and may correct only PERSON A's face/head using
all user identity references while preserving the scene, pose, clothing and
PERSON B.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import re
import sys
import threading
import time
from typing import Any

VERSION = "v229-selfie-canonical-two-stage-google-2026-07-28"
_HANDLER_FLAG = "_selfie_v229_canonical_handler_bound"
_STARTED = False
_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)"


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
    timeout_s = max(300.0, float(os.environ.get("GEMINI_SELFIE_TIMEOUT_S", "360") or 360))
    timeout = httpx.Timeout(timeout_s, connect=45.0, read=timeout_s, write=180.0, pool=45.0)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    errors: list[str] = []

    _log(
        "AI_SELFIE_V229_STAGE_START stage=%s provider=Google-Gemini-direct key_fp=%s models=%s refs=%s",
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
                payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
                try:
                    response = await client.post(
                        f"{_base_url()}/models/{model}:generateContent",
                        headers=headers,
                        json=payload,
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
                            runtime.AI_SELFIE_LAST_IMAGE_SIZE = os.environ.get("GEMINI_SELFIE_IMAGE_SIZE", "2K")
                            runtime.AI_SELFIE_LAST_STAGE = stage
                        _log(
                            "AI_SELFIE_V229_STAGE_SUCCESS stage=%s model=%s refs=%s bytes=%s key_fp=%s",
                            stage, model, len(labeled_images), len(output), _fingerprint(key),
                        )
                        return output, model
                    errors.append(f"{stage}/{model}: response contained no final image")
                except Exception as exc:
                    errors.append(f"{stage}/{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Direct Google Gemini failed: " + " | ".join(errors[-8:]))


def _identity_refs(user_images: list[bytes], slug: str) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v213_user_identity_lock as identity

    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    hero_paths = base._reference_paths(runtime, slug)
    if len(user_images) != 3 or len(hero_paths) != 3:
        raise RuntimeError(f"user photos={len(user_images)}/3, hero refs={len(hero_paths)}/3")

    user_refs: list[tuple[str, bytes]] = []
    for idx, raw in enumerate(user_images, 1):
        user_refs.append((f"USER ORIGINAL {idx}: body, age, build, hair and identity", bytes(raw)))
        user_refs.append((f"USER FACE CROP {idx}: PRIMARY AUTHORITATIVE FACE IDENTITY", identity._user_face_crop(bytes(raw))))
    hero_refs = [(f"HERO PORTRAIT {idx}: authoritative PERSON B identity", path.read_bytes()) for idx, path in enumerate(hero_paths, 1)]
    return user_refs, hero_refs


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool) -> str:
    scene_rule = (
        "The first image is the authoritative scene base. Preserve its exact architecture, furniture, object positions, camera viewpoint, crop, perspective, lighting direction and color. Add people without redesigning the place. "
        if has_scene_image else
        f"Create the requested scene faithfully: {scene}. "
    )
    return (
        "Create one photorealistic vertical image with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}"
        "PERSON A is the user. Six user references follow as three originals paired with three tight face crops. "
        "The face crops are the highest-priority identity anchors. Preserve PERSON A's exact head width and height, forehead, hairline, eye shape and spacing, eyebrows, nose bridge and tip, mouth, cheeks, jawline, chin, ears, skin tone, apparent age, natural asymmetry and body build. "
        "Do not beautify, slim, masculinize, feminize, rejuvenate, average, sharpen, broaden or replace PERSON A with a generic similar face. Keep the user's face large, clear, unobstructed and near-frontal or mild three-quarter. "
        f"PERSON B is {name}; the three hero portraits define PERSON B. Keep identities separate and do not transfer features. "
        "Natural anatomy, realistic skin texture and optics. No text, logos, watermark or interface."
    )


def _stage2_prompt(name: str) -> str:
    return (
        "IDENTITY CORRECTION PASS. The first image is the authoritative completed composition. Return the same photograph and change ONLY PERSON A's face/head where necessary to match the user references. "
        "Pixel-lock everything else: PERSON B, both bodies, pose, hands, clothing, table, food, furniture, architecture, background people, camera position, perspective, crop, lighting, shadows, colors and resolution. Do not move, add or remove objects. "
        "The next six references are three originals and three tight face crops of PERSON A. The face crops are decisive. Match exact craniofacial geometry: head width/height, forehead, hairline, eye shape/spacing, eyebrows, nose, philtrum, lips, cheeks, jaw, chin, ears, skin tone, age and natural asymmetry. Preserve the user's real fuller facial proportions and body build; do not slim or beautify. "
        f"PERSON B is {name}; the final three references protect PERSON B's identity. Do not alter PERSON B. "
        "This is a localized identity repair, not a new composition. Output one photorealistic image only."
    )


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
    photos = v219._photos(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or context.user_data.get("cs215_scene_text") or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == v215.SCENE_IMAGE else None

    if not meta or len(photos) != 3 or shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON} or not v219._scene_ready(context):
        await delivery._safe_text(message, "❌ Не хватает данных: нужны 3 фото пользователя, герой, тип кадра и сцена.")
        return False
    if not _key():
        await delivery._safe_text(message, "❌ Отсутствует GEMINI_IMAGE_API_KEY. CometAPI и альтернативные ключи для этого режима отключены.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    result = {"ok": False}
    user_refs, hero_refs = _identity_refs(photos, slug)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE: preserve exact location and composition", bytes(scene_image)))
    stage1_refs.extend(user_refs)
    stage1_refs.extend(hero_refs)

    async def action() -> bool:
        try:
            await delivery._safe_text(message, f"⏳ Этап 1/2: создаю композицию через прямой Google Gemini. Референсов: {len(stage1_refs)}.")
            stage1, model1 = await _call_google(
                _stage1_prompt(str(meta['name']), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "composition",
            )
            await delivery._safe_text(message, "🧬 Этап 2/2: фиксирую личность пользователя, не меняя сцену и героя.")
            stage2_refs = [("AUTHORITATIVE GENERATED BASE: edit only PERSON A face/head", stage1)] + user_refs + hero_refs
            final, model2 = await _call_google(_stage2_prompt(str(meta['name'])), stage2_refs, "user_identity_fix")

            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                f"Маршрут: прямой Google Gemini API · 2 этапа · модели: {model1} → {model2}.\n"
                f"Идентичность пользователя: 3 оригинала + 3 кропа лица. CometAPI не используется. "
                "Изображение создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Данные пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V229 canonical two-stage selfie failed", exc)
            await delivery._safe_text(message, f"❌ Двухэтапный Google Gemini не создал изображение. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v229_two_stage_google",
        "remember_payload": {"character": slug, "provider": "google_gemini_direct", "stages": 2, "user_originals": 3, "user_face_crops": 3, "hero_refs": 3, "scene_image": has_scene_image},
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


async def generation_callback(update: Any, context: Any) -> None:
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


def _is_legacy_generation_handler(handler: Any) -> bool:
    callback = getattr(handler, "callback", None)
    if callback is generation_callback:
        return False
    module = str(getattr(callback, "__module__", ""))
    name = str(getattr(callback, "__name__", ""))
    pattern = str(getattr(handler, "pattern", "") or "")
    return (
        module.startswith("neyrobot_prod.selfie_")
        and ("generation" in name or "callback" in name)
        and any(token in pattern for token in ("cs201:preset", "generate_current", "reuse:repeat"))
    )


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)) or not isinstance(getattr(app, "handlers", None), dict):
        return False
    # Remove every legacy generation callback from the live handler table.
    for group, handlers in list(app.handlers.items()):
        app.handlers[group] = [handler for handler in handlers if not _is_legacy_generation_handler(handler)]
    if not getattr(app, _HANDLER_FLAG, False):
        from telegram.ext import CallbackQueryHandler
        app.add_handler(CallbackQueryHandler(generation_callback, pattern=_GENERATION_PATTERN), group=-20000)
        setattr(app, _HANDLER_FLAG, True)
    return True


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v220_runtime_marker as v220

    # Replace all callable aliases, not just their visible version markers.
    base._generate = generate
    v208._generate = generate
    v215.generate = generate
    v217.generate = generate
    v219.generate = generate
    v219._comet_generate = _call_google
    for module in (v218, v219, v220):
        module.VERSION = VERSION

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v229-canonical-handler-direct-google-two-stage"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_ACTIVE_KEY_FINGERPRINT = _fingerprint(_key())
        runtime.AI_SELFIE_CONFIGURED = bool(_key())
        runtime.AI_SELFIE_GENERATION_STAGES = 2
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
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
                _log("V229 canonical owner patch failed: %r", exc)
            time.sleep(0.10)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v229-canonical-two-stage").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "generate", "generation_callback", "patch_runtime", "install_async", "install"]
