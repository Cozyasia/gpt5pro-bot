# -*- coding: utf-8 -*-
"""Celebrity Selfie V204: CometAPI-backed four-reference Gemini editing.

Uses the existing CometAPI account instead of requiring a separate Google key.
The request contains exactly four images: user selfie + three fixed character
references. Direct Google Gemini remains an optional fallback only when its key
is present. The legacy one-image Comet/Nano Banana path is never used here.
"""
from __future__ import annotations

import base64
import contextlib
import os
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

VERSION = "v204-selfie-comet-multireference-2026-07-25"
_BUILDER_HOOKED = False
_WORKER_STARTED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _comet_key() -> str:
    return (os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY") or "").strip()


def _google_key() -> str:
    return (os.environ.get("GEMINI_IMAGE_API_KEY") or "").strip()


def _provider() -> str:
    if _comet_key():
        return "comet"
    if _google_key():
        return "google"
    return "off"


def _storage_root(mod: Any) -> Path:
    """Always prefer the Render persistent disk over source-tree paths."""
    candidates = [Path("/data/celebrity_selfie")]
    db_path = Path(str(getattr(mod, "DB_PATH", "/data/subs.db") or "/data/subs.db")).resolve()
    candidates.append(db_path.parent / "celebrity_selfie")
    configured = (os.environ.get("CELEBRITY_SELFIE_DATA_DIR") or "").strip()
    if configured and not configured.startswith("/opt/render/project/src"):
        candidates.append(Path(configured))
    candidates.append(Path("/tmp/celebrity_selfie"))
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".v204_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            os.environ["CELEBRITY_SELFIE_DATA_DIR"] = str(path)
            return path
        except Exception:
            continue
    return Path("/tmp/celebrity_selfie")


def _models() -> list[str]:
    raw = (
        os.environ.get("COMET_SELFIE_MODELS")
        or os.environ.get("COMET_SELFIE_MODEL")
        or "gemini-3-pro-image,gemini-3-pro-image-preview,gemini-3.1-flash-image-preview"
    )
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _strict_prompt(character_name: str, scene_text: str, aspect: str) -> str:
    return (
        "Create one photorealistic vertical smartphone selfie with exactly two people. "
        f"Scene: {scene_text}. Aspect ratio {aspect}. "
        "REFERENCE 1 is the USER. Preserve only this person's face, age, beard, hairline, eye shape, nose, mouth, jaw and skin texture. "
        f"REFERENCES 2, 3 and 4 are three photographs of the SAME second person, {character_name}. "
        "Use all three together to reconstruct that second person's identity. Do not invent a generic substitute. "
        "Do not merge, average, swap, rejuvenate, beautify or duplicate either face. "
        "Keep both identities separate and recognisable. Match natural perspective, lens distortion, lighting, scale and skin texture. "
        "Correct hands and anatomy. No text, logos, watermarks or interface elements. "
        "The result is fictional AI-generated content, not proof of a real meeting or endorsement."
    )


def _parts(images: list[tuple[str, str]], prompt: str, *, camel_case: bool) -> list[dict[str, Any]]:
    labels = (
        "REFERENCE 1 — USER SELFIE",
        "REFERENCE 2 — CHARACTER PHOTO A",
        "REFERENCE 3 — CHARACTER PHOTO B",
        "REFERENCE 4 — CHARACTER PHOTO C",
    )
    result: list[dict[str, Any]] = [{"text": prompt}]
    for index, (data, mime) in enumerate(images):
        result.append({"text": labels[index]})
        if camel_case:
            result.append({"inlineData": {"mimeType": mime, "data": data}})
        else:
            result.append({"inline_data": {"mime_type": mime, "data": data}})
    return result


def _payload(images: list[tuple[str, str]], prompt: str, *, camel_case: bool, compatibility: bool, aspect: str, size: str) -> dict[str, Any]:
    generation: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
    if not compatibility:
        generation["imageConfig"] = {"aspectRatio": aspect, "imageSize": size}
    return {
        "contents": [{"role": "user", "parts": _parts(images, prompt, camel_case=camel_case)}],
        "generationConfig": generation,
    }


def _extract_final_image(data: Any) -> bytes | None:
    """Use the last non-thought image; newer Gemini responses can include drafts."""
    candidates = data.get("candidates") if isinstance(data, dict) else None
    found: list[bytes] = []
    for candidate in candidates or []:
        content = (candidate or {}).get("content") or {}
        for part in content.get("parts") or []:
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            inline = part.get("inlineData") or part.get("inline_data") or {}
            encoded = inline.get("data") if isinstance(inline, dict) else None
            if not isinstance(encoded, str) or len(encoded) < 100:
                continue
            with contextlib.suppress(Exception):
                raw = base64.b64decode(encoded.split(",", 1)[-1], validate=False)
                if len(raw) > 1024:
                    found.append(raw)
    return found[-1] if found else None


async def _comet_generate(mod: Any, image_bytes: bytes, slug: str, scene_text: str) -> bytes:
    from neyrobot_prod import celebrity_selfie as base

    key = _comet_key()
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")
    refs = base._reference_paths(mod, slug)
    if len(refs) != 3:
        raise RuntimeError(f"character references: {len(refs)}/3")

    prepared = [base._prepare_image(mod, image_bytes)]
    prepared.extend(base._prepare_image(mod, path.read_bytes()) for path in refs)
    if len(prepared) != 4:
        raise RuntimeError("exactly four images are required")

    meta = base.CHARACTERS.get(slug) or {}
    character_name = str(meta.get("name") or slug)
    aspect = base._aspect_ratio()
    size = base._image_size()
    prompt = _strict_prompt(character_name, scene_text, aspect)
    base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    headers = {
        "Authorization": f"Bearer {key}",
        "x-goog-api-key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout_s = max(60.0, float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300") or 300))
    errors: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout_s, connect=25.0)) as client:
        for model in _models():
            for camel_case, compatibility in ((True, False), (False, False), (True, True), (False, True)):
                try:
                    response = await client.post(
                        f"{base_url}/v1beta/models/{model}:generateContent",
                        headers=headers,
                        json=_payload(
                            prepared,
                            prompt,
                            camel_case=camel_case,
                            compatibility=compatibility,
                            aspect=aspect,
                            size=size,
                        ),
                    )
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
                    continue
                if response.status_code >= 400:
                    detail = response.text[:900]
                    errors.append(f"{model}: HTTP {response.status_code}: {detail}")
                    continue
                try:
                    body = response.json()
                except Exception as exc:
                    errors.append(f"{model}: invalid JSON: {exc}")
                    continue
                output = _extract_final_image(body)
                if output:
                    return output
                errors.append(f"{model}: no final non-thought image")
    raise RuntimeError("Comet multi-reference Gemini failed: " + " | ".join(errors[-8:]))


async def _generate_image(mod: Any, image_bytes: bytes, slug: str, scene_text: str) -> tuple[bytes, str]:
    if _comet_key():
        return await _comet_generate(mod, image_bytes, slug, scene_text), "CometAPI / Gemini"
    if _google_key():
        from neyrobot_prod import celebrity_selfie as base
        meta = base.CHARACTERS.get(slug) or {}
        name = str(meta.get("name") or slug)
        prompt = f"Фикционное AI-селфи пользователя с {name}. Сцена: {scene_text}."
        return await base.generate_direct(mod, image_bytes, prompt, "", character_slug=slug), "Google Gemini"
    raise RuntimeError("Neither COMET_API_KEY nor GEMINI_IMAGE_API_KEY is configured")


async def _send_result(mod: Any, update: Any, context: Any, *, image: bytes, slug: str, scene_text: str) -> bool:
    from neyrobot_prod import celebrity_selfie as base

    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    try:
        provider = "CometAPI / Gemini" if _comet_key() else "Google Gemini"
        await update.effective_message.reply_text(
            f"⏳ Создаю AI-селфи через {provider}: ваше селфи + 3 JPEG-референса героя."
        )
        output, used_provider = await _generate_image(mod, image, slug, scene_text)
        if len(output) < 1024:
            raise RuntimeError("provider returned an empty image")
        bio = BytesIO(output)
        bio.name = "celebrity_selfie_v204.png"
        caption = (
            f"🤳 AI-селфи с персонажем «{name}» готово ✅\n"
            f"Маршрут: {used_provider}, 4 референса. Изображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
        )
        if bool(getattr(mod, "AI_SELFIE_SEND_AS_DOCUMENT", True)):
            input_file = getattr(mod, "InputFile", None)
            await update.effective_message.reply_document(input_file(bio) if callable(input_file) else bio, caption=caption)
        else:
            await update.effective_message.reply_photo(photo=output, caption=caption)
        return True
    except Exception as exc:
        logger = getattr(mod, "log", None)
        if logger:
            with contextlib.suppress(Exception):
                logger.exception("Celebrity Selfie V204 failed: %s", exc)
        await update.effective_message.reply_text(
            "❌ Многореференсное AI-селфи не создано. Случайный однореференсный Comet-маршрут не использовался. "
            f"Средства за неуспешный результат не должны списываться. Причина: {str(exc)[:1100]}"
        )
        return False


async def generate(mod: Any, update: Any, context: Any, scene_text: str) -> None:
    from neyrobot_prod import celebrity_selfie as base

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    if not meta:
        await update.effective_message.reply_text("Сначала выберите героя.", reply_markup=base._character_kb(mod))
        return
    if not base._character_ready(mod, slug):
        await update.effective_message.reply_text(
            f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(mod, slug)}.",
            reply_markup=base._character_kb(mod),
        )
        return
    if _provider() == "off":
        await update.effective_message.reply_text(
            "❌ Не найден ни COMET_API_KEY, ни GEMINI_IMAGE_API_KEY. Для этого режима нужен хотя бы один из них."
        )
        return
    image = base._cached_photo(mod, update.effective_user.id)
    if not image:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await update.effective_message.reply_text("Пришлите селфи ещё раз.", reply_markup=base._main_kb(mod))
        return

    paid_runner = getattr(mod, "_try_pay_then_do", None)
    if not callable(paid_runner):
        await update.effective_message.reply_text("❌ Платёжный guard генераций не найден. Запуск остановлен.")
        return

    async def action() -> bool:
        return await _send_result(mod, update, context, image=image, slug=slug, scene_text=scene_text)

    cost = max(0.0, float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20))
    await paid_runner(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        action,
        remember_kind="celebrity_selfie_v204",
        remember_payload={
            "character": slug,
            "scene": scene_text,
            "references": 4,
            "provider": _provider(),
        },
    )


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    mod = _runtime_module()
    try:
        if mod is None:
            return
        lines = [
            "🤳 Celebrity Selfie diagnostic",
            f"version={VERSION}",
            "route=v204-comet-multireference",
            f"provider={_provider()}",
            f"comet_key={'on' if bool(_comet_key()) else 'off'}",
            f"gemini_key={'on' if bool(_google_key()) else 'off'}",
            f"models={','.join(_models())}",
            f"storage={base._storage_root(mod)}",
            f"roman_abramovich={base._character_status(mod, 'roman_abramovich')}",
            f"ready={'on' if base._character_ready(mod, 'roman_abramovich') else 'off'}",
            "references_per_request=4",
            "legacy_single_image_comet=off",
        ]
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def patch() -> bool:
    from neyrobot_prod import celebrity_selfie as base

    base._storage_root = _storage_root
    generate._selfie_v204 = True
    base._generate = generate
    mod = _runtime_module()
    if mod is not None:
        mod.CELEBRITY_SELFIE_VERSION = VERSION
        mod.AI_SELFIE_RUNTIME_VERSION = VERSION
        mod.CELEBRITY_SELFIE_ROUTE = "v204-comet-multireference"
    return True


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return False
    flag = "_celebrity_selfie_v204_builder"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, flag, False):
            app.add_handler(CommandHandler("diag_selfie", diagnostic), group=-70)
            setattr(app, flag, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True
    return True


def install_async() -> None:
    global _WORKER_STARTED
    install_builder_hook()
    patch()
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            try:
                patch()
                mod = _runtime_module()
                if mod is not None and callable(getattr(mod, "_try_pay_then_do", None)):
                    stable += 1
                    if stable >= 300:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-celebrity-selfie-v204", daemon=True).start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION", "_provider", "_storage_root", "_payload", "_extract_final_image",
    "_comet_generate", "generate", "diagnostic", "patch", "install_builder_hook",
    "install_async", "install",
]
