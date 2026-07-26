# -*- coding: utf-8 -*-
"""V217: three user selfies + three hero references with equal identity priority.

This layer is installed after V209 and owns the public AI-selfie callbacks, media
capture and generation path. It does not touch medicine, medical cards, billing,
menus, video or other entertainment modes.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from io import BytesIO
from typing import Any

VERSION = "v217-selfie-user-triref-equal-priority-2026-07-27"
USER_REFS = 3
HERO_REFS = 3
TOTAL_REFS = USER_REFS + HERO_REFS
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


def _instruction_for_next(count: int) -> str:
    if count == 1:
        return "✅ Селфи 1/3 принято. Пришлите селфи 2/3: лёгкий поворот головы на 15–30° в другую сторону."
    if count == 2:
        return "✅ Селфи 2/3 принято. Пришлите селфи 3/3: ещё один естественный ракурс при хорошем освещении."
    return ""


async def public_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    mod = _runtime()
    query = getattr(update, "callback_query", None)
    if mod is None or query is None:
        return
    data = str(query.data or "")
    with contextlib.suppress(Exception):
        await query.answer()

    if data in {"cs201:open", "act:fun:aiselfie", "fun:aiselfie"}:
        v208._clear(context, keep_photos=True)
        base._activate(mod, context, query.from_user.id)
        await query.message.reply_text(
            "🤳 AI-селфи со звездой\n\n"
            "1) загрузите три свои фотографии: анфас и два разных ракурса; "
            "2) выберите страну и героя; 3) выберите сцену. "
            "В генерации используются 3 фото пользователя и 3 JPEG героя с равным приоритетом личности.",
            reply_markup=base._main_kb(mod),
        )
        raise ApplicationHandlerStop

    if data in {"cs201:photo", "act:fun:aiselfie_upload"}:
        base._activate(mod, context, query.from_user.id)
        _reset_photos(context)
        context.user_data["awaiting_ai_selfie_photo"] = True
        await query.message.reply_text(
            "📸 Селфи 1/3: пришлите чёткое фото анфас без фильтров. "
            "Лицо должно быть полностью видно, без очков, размытия и закрывающих предметов."
        )
        raise ApplicationHandlerStop

    if data in {"cs201:last", "act:fun:aiselfie_last"}:
        base._activate(mod, context, query.from_user.id)
        cached = base._cached_photo(mod, query.from_user.id)
        _reset_photos(context, cached if cached else None)
        context.user_data["awaiting_ai_selfie_photo"] = True
        if cached:
            await query.message.reply_text(
                "✅ Последнее фото использовано как селфи 1/3. Пришлите селфи 2/3 с лёгким поворотом головы."
            )
        else:
            await query.message.reply_text("Последнего фото нет. Пришлите селфи 1/3 анфас.")
        raise ApplicationHandlerStop

    if data in {"cs201:characters", "act:fun:aiselfie_custom"} or data.startswith("act:fun:as_preset_"):
        base._activate(mod, context, query.from_user.id)
        if len(_photos(context)) != USER_REFS:
            context.user_data["awaiting_ai_selfie_photo"] = True
            await query.message.reply_text(
                f"Сначала пришлите три селфи пользователя. Сейчас получено {len(_photos(context))}/{USER_REFS}.",
                reply_markup=base._main_kb(mod),
            )
        else:
            await query.message.reply_text("⭐ Выберите страну героя:", reply_markup=v208._country_kb(base, mod))
        raise ApplicationHandlerStop

    await v208._v217_original_public_callback(update, context)


async def public_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    mod = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if mod is None or user is None or message is None or not base._active(mod, context, user.id):
        return
    if not context.user_data.get("awaiting_ai_selfie_photo") and not (0 < len(_photos(context)) < USER_REFS):
        return

    raw, url = await base._download_photo_message(message)
    if not raw:
        return
    base._activate(mod, context, user.id)
    count = _append_photo(context, raw)
    # Preserve compatibility with the bot's global last-photo cache without using
    # it as the canonical three-reference store.
    with contextlib.suppress(Exception):
        base._cache_photo(mod, user.id, raw, url)

    if count < USER_REFS:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await message.reply_text(_instruction_for_next(count))
    else:
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        await message.reply_text(
            "✅ Все 3/3 селфи пользователя приняты. Выберите страну героя:",
            reply_markup=v208._country_kb(base, mod),
        )
    raise ApplicationHandlerStop


async def reject_non_photo_selfie(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    mod = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if mod is None or user is None or message is None or not base._active(mod, context, int(user.id)):
        return
    await message.reply_text(
        "⚠️ Для AI-селфи нужны три отдельные фотографии, не видео. "
        "Пришлите: 1/3 анфас, 2/3 лёгкий поворот, 3/3 ещё один естественный ракурс."
    )
    raise ApplicationHandlerStop


async def comet_generate(user_images: list[bytes], slug: str, scene: str) -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator

    mod = _runtime()
    refs = base._reference_paths(mod, slug)
    if len(user_images) != USER_REFS or len(refs) != HERO_REFS:
        raise RuntimeError(
            f"user selfies={len(user_images)}/{USER_REFS}, character refs={len(refs)}/{HERO_REFS}"
        )

    prepared = [base._prepare_image(mod, raw) for raw in user_images]
    prepared.extend(base._prepare_image(mod, path.read_bytes()) for path in refs)
    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    prompt = (
        "Create one photorealistic vertical arm's-length smartphone selfie with exactly two people. "
        f"Scene: {scene}. Aspect ratio {base._aspect_ratio()}. "
        "REFERENCES 1, 2 and 3 are three photographs of the SAME USER. Reconstruct the user from all three references. "
        "Preserve the user's exact facial geometry, apparent age, head shape, eye spacing and shape, eyebrows, nose, mouth, "
        "jawline, beard, hairline, skin tone and distinctive asymmetries. Do not beautify, rejuvenate or replace the user with "
        "a generic similar person. "
        f"REFERENCES 4, 5 and 6 are three photographs of the SAME selected character, {name}. Reconstruct that person from all three. "
        "Give the USER and the selected character exactly equal identity priority and equal facial fidelity. Keep them as two "
        "separate, recognisable people. Never merge, average, swap, duplicate or transfer facial features between them. "
        "Match natural lens perspective, scale, lighting and realistic skin texture. Correct hands and anatomy. "
        "No text, logos, watermarks or interface elements. Fictional AI-generated scene, not evidence of a real meeting or endorsement."
    )

    key = generator._comet_key()
    base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")
    headers = {
        "Authorization": f"Bearer {key}",
        "x-goog-api-key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    import httpx

    labels = (
        "REFERENCE 1 — USER SELFIE FRONT",
        "REFERENCE 2 — USER SELFIE ANGLE A",
        "REFERENCE 3 — USER SELFIE ANGLE B",
        "REFERENCE 4 — CHARACTER PHOTO A",
        "REFERENCE 5 — CHARACTER PHOTO B",
        "REFERENCE 6 — CHARACTER PHOTO C",
    )
    errors: list[str] = []
    timeout_s = max(60.0, float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300")))
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_s, connect=25.0),
    ) as client:
        for model in generator._models():
            for camel, compatibility in ((True, False), (False, False), (True, True), (False, True)):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, (data, mime) in zip(labels, prepared):
                    parts.append({"text": label})
                    if camel:
                        parts.append({"inlineData": {"mimeType": mime, "data": data}})
                    else:
                        parts.append({"inline_data": {"mime_type": mime, "data": data}})
                config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
                if not compatibility:
                    config["imageConfig"] = {
                        "aspectRatio": base._aspect_ratio(),
                        "imageSize": base._image_size(),
                    }
                try:
                    response = await client.post(
                        f"{base_url}/v1beta/models/{model}:generateContent",
                        headers=headers,
                        json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config},
                    )
                    if response.status_code >= 400:
                        errors.append(f"{model}: HTTP {response.status_code}: {response.text[:300]}")
                        continue
                    output = generator._extract_final_image(response.json())
                    if output:
                        return output
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Comet six-reference generation failed: " + " | ".join(errors[-6:]))


async def generate(update: Any, context: Any, scene: str) -> None:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    mod = _runtime()
    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    photos = _photos(context)
    if not meta:
        await update.effective_message.reply_text(
            "Сначала выберите страну и героя.", reply_markup=v208._country_kb(base, mod)
        )
        return
    if not base._character_ready(mod, slug):
        await update.effective_message.reply_text(
            f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(mod, slug)}."
        )
        return
    if len(photos) != USER_REFS:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await update.effective_message.reply_text(
            f"Нужны три селфи пользователя. Сейчас получено {len(photos)}/{USER_REFS}.",
            reply_markup=base._main_kb(mod),
        )
        return

    runner = getattr(mod, "_try_pay_then_do", None)
    if not callable(runner):
        await update.effective_message.reply_text("❌ Платёжный guard генераций не найден.")
        return

    async def action() -> bool:
        try:
            await update.effective_message.reply_text(
                "⏳ Создаю AI-селфи: 3 селфи пользователя + 3 JPEG героя. "
                "Обе личности имеют равный приоритет."
            )
            output = await comet_generate(photos, slug, scene)
            bio = BytesIO(output)
            bio.name = "celebrity_selfie_v217.png"
            caption = (
                f"🤳 AI-селфи с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут: CometAPI / Gemini, 6 референсов — 3 пользователя + 3 героя. "
                "Изображение сгенерировано ИИ."
            )
            if bool(getattr(mod, "AI_SELFIE_SEND_AS_DOCUMENT", True)):
                input_file = getattr(mod, "InputFile", None)
                await update.effective_message.reply_document(
                    input_file(bio) if callable(input_file) else bio,
                    caption=caption,
                )
            else:
                await update.effective_message.reply_photo(photo=output, caption=caption)
            v208._clear(context, keep_photos=False)
            setter = getattr(mod, "_set_mode_clean", None)
            if callable(setter):
                setter(int(update.effective_user.id), "Развлечения", "")
            return True
        except Exception as exc:
            await update.effective_message.reply_text(
                f"❌ AI-селфи не создано; средства не должны списываться. Причина: {str(exc)[:1000]}"
            )
            return False

    await runner(
        update,
        context,
        update.effective_user.id,
        "img",
        max(0.0, float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)),
        action,
        remember_kind="celebrity_selfie_v217",
        remember_payload={
            "character": slug,
            "scene": scene,
            "references": TOTAL_REFS,
            "user_references": USER_REFS,
            "hero_references": HERO_REFS,
            "provider": "comet",
        },
    )


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    mod = _runtime()
    try:
        if mod is None:
            return
        root = base._storage_root(mod)
        lines = [
            "💾 Selfie Storage diagnostic",
            f"version={VERSION}",
            f"storage={root}",
            f"data_is_mount={'on' if os.path.ismount('/data') else 'off'}",
            "persistent_storage=on",
            f"characters={len(base.CHARACTERS)}",
            "generator=v217-comet-six-reference",
            f"user_references={USER_REFS}",
            f"hero_references={HERO_REFS}",
            f"references_per_request={TOTAL_REFS}",
            "identity_priority=user_equal_hero",
        ]
        for slug in base.CHARACTERS:
            lines.append(
                f"{slug}={base._character_status(mod, slug)} ready={'on' if base._character_ready(mod, slug) else 'off'}"
            )
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator
    from neyrobot_prod import selfie_commands_v206 as commands
    from neyrobot_prod import selfie_runtime_v207 as legacy_runtime
    from neyrobot_prod import selfie_storage_v205 as storage
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209

    if not hasattr(v208, "_v217_original_public_callback"):
        v208._v217_original_public_callback = v208._public_callback

    v208.VERSION = VERSION
    v208._photos = _photos
    v208._reset_photos = _reset_photos
    v208._append_photo = _append_photo
    v208._public_callback = public_callback
    v208._public_media = public_media
    v208._comet_generate = comet_generate
    v208._generate = generate
    v208._diag_storage = diagnostic

    base.callback = public_callback
    base.media_entry = public_media
    base._generate = generate
    generator.VERSION = VERSION
    commands.VERSION = VERSION
    legacy_runtime.VERSION = VERSION
    storage.VERSION = VERSION
    storage.diagnostic = diagnostic

    v209.VERSION = VERSION
    v209.reject_non_photo_selfie = reject_non_photo_selfie

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v217-comet-six-reference-equal-priority"
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
    return True


def install_async() -> None:
    global _STARTED
    patch_runtime()
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        # Later legacy/bootstrap workers can republish old handlers and versions.
        # Keep V217 as the sole owner throughout the running process.
        for _ in range(21600):
            with contextlib.suppress(Exception):
                patch_runtime()
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v217-triref").start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "USER_REFS",
    "HERO_REFS",
    "TOTAL_REFS",
    "public_callback",
    "public_media",
    "reject_non_photo_selfie",
    "comet_generate",
    "generate",
    "diagnostic",
    "patch_runtime",
    "install_async",
    "install",
]
