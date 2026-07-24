# -*- coding: utf-8 -*-
"""Isolated direct-Gemini runtime for Celebrity Selfie.

This module patches only ``main._run_ai_selfie_image``. Billing remains owned by
``main._start_ai_selfie`` and every non-selfie feature remains untouched.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
import threading
import time
from io import BytesIO
from typing import Any

import httpx

VERSION = "v119-celebrity-selfie-gemini-direct-2026-07-25"
_PATCH_FLAG = "_CELEBRITY_SELFIE_GEMINI_PATCHED"
_WORKER_STARTED = False
_DIRECT_PROVIDERS = {"gemini", "google", "google-gemini", "gemini-direct"}


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", "off"}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _models() -> list[str]:
    values = [
        _env("GEMINI_IMAGE_MODEL", "gemini-3-pro-image"),
        _env("GEMINI_IMAGE_FALLBACK_MODEL", "gemini-3.1-flash-image"),
    ]
    return list(dict.fromkeys(value for value in values if value))


def _image_size() -> str:
    value = _env("AI_SELFIE_IMAGE_SIZE", "2K").upper()
    return value if value in {"512", "1K", "2K", "4K"} else "2K"


def _aspect_ratio() -> str:
    value = _env("AI_SELFIE_DEFAULT_ASPECT", "4:5")
    allowed = {"1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"}
    return value if value in allowed else "4:5"


def _prompt(mod: Any, user_prompt: str, preset_prompt: str = "") -> str:
    builder = getattr(mod, "_ai_selfie_final_prompt", None)
    if callable(builder):
        with contextlib.suppress(Exception):
            base = str(builder(user_prompt, preset_prompt) or "").strip()
            if base:
                return base + " " + _identity_guard()
    request = (user_prompt or preset_prompt or "realistic selfie with a celebrity").strip()
    return f"Create a realistic smartphone selfie from the supplied user photo. User request: {request[:800]}. {_identity_guard()}"


def _identity_guard() -> str:
    return (
        "Treat the uploaded person as the user's identity reference. Preserve their facial geometry, age, skin tone, eye shape, "
        "hairline and distinctive features. Keep the user and the requested public figure as two separate recognizable people; "
        "do not merge, average, swap or duplicate their faces. Compose a plausible arm's-length smartphone selfie with consistent "
        "lighting, perspective, scale and skin texture. Keep hands anatomically correct. No text, logos, watermarks or interface elements. "
        "The result is a fictional AI-generated fan scene, not evidence of a real meeting or endorsement."
    )


def _extract_b64(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("type") == "image":
            data = value.get("data") or value.get("base64") or value.get("b64_json")
            if isinstance(data, str) and len(data) > 100:
                return data
        for key in ("inlineData", "inline_data", "output_image", "image", "generated_image"):
            item = value.get(key)
            if isinstance(item, dict):
                data = item.get("data") or item.get("base64") or item.get("b64_json")
                if isinstance(data, str) and len(data) > 100:
                    return data
        for key in ("candidates", "content", "parts", "steps", "output", "data", "result", "response"):
            found = _extract_b64(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _extract_b64(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _extract_b64(item)
            if found:
                return found
    return ""


def _decode_image(value: Any) -> bytes | None:
    encoded = _extract_b64(value)
    if not encoded:
        return None
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        decoded = base64.b64decode(encoded, validate=False)
    except Exception:
        return None
    return decoded if len(decoded) > 100 else None


def _payload(prompt: str, image_b64: str, mime: str, *, compatibility: bool) -> dict[str, Any]:
    config: dict[str, Any] = {
        "responseModalities": ["TEXT", "IMAGE"] if compatibility else ["IMAGE"],
    }
    if not compatibility:
        config["responseFormat"] = {
            "image": {
                "aspectRatio": _aspect_ratio(),
                "imageSize": _image_size(),
            }
        }
    return {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": image_b64}},
            ],
        }],
        "generationConfig": config,
    }


async def generate_direct(mod: Any, image_bytes: bytes, user_prompt: str, preset_prompt: str = "") -> bytes:
    key = _env("GEMINI_IMAGE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")
    if not image_bytes:
        raise RuntimeError("selfie image is empty")

    prepare = getattr(mod, "_prepare_reference_image_for_gemini", None)
    if not callable(prepare):
        raise RuntimeError("runtime selfie image preprocessor is unavailable")
    image_b64, mime = prepare(image_bytes, int(_env("AI_SELFIE_MAX_SIDE", "1536") or 1536))
    mime = mime or "image/jpeg"
    prompt = _prompt(mod, user_prompt, preset_prompt)
    base_url = _env("GEMINI_IMAGE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    timeout_s = max(30.0, float(_env("GEMINI_IMAGE_TIMEOUT_S", "180") or 180))
    deadline = time.monotonic() + timeout_s
    errors: list[str] = []
    headers = {"x-goog-api-key": key, "Accept": "application/json", "Content-Type": "application/json"}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for model in _models():
            for compatibility in (False, True):
                remaining = deadline - time.monotonic()
                if remaining <= 1:
                    break
                url = f"{base_url}/models/{model}:generateContent"
                try:
                    response = await client.post(
                        url,
                        headers=headers,
                        json=_payload(prompt, image_b64, mime, compatibility=compatibility),
                        timeout=httpx.Timeout(min(remaining, 120.0), connect=20.0, write=60.0, read=min(remaining, 120.0)),
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    errors.append(f"{model}: {type(exc).__name__}")
                    continue
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
                    continue

                if response.status_code >= 400:
                    try:
                        detail = json.dumps(response.json(), ensure_ascii=False)[:600]
                    except Exception:
                        detail = response.text[:600]
                    errors.append(f"{model}: HTTP {response.status_code}: {detail}")
                    continue

                helper = getattr(mod, "_image_bytes_from_response", None)
                if callable(helper):
                    with contextlib.suppress(Exception):
                        output = await helper(response, client)
                        if output:
                            return output
                try:
                    payload = response.json()
                except Exception as exc:
                    errors.append(f"{model}: invalid JSON: {exc}")
                    continue
                output = _decode_image(payload)
                if output:
                    return output
                errors.append(f"{model}: response contained no image")

    raise RuntimeError("Direct Gemini image edit failed: " + " | ".join(errors[-6:]))


def patch_runtime(mod: Any) -> bool:
    current = getattr(mod, "_run_ai_selfie_image", None)
    if not callable(current):
        return False
    if getattr(current, "_celebrity_selfie_direct_gemini", False):
        setattr(mod, _PATCH_FLAG, True)
        setattr(mod, "AI_SELFIE_RUNTIME_VERSION", VERSION)
        return True

    original = current

    async def run(update: Any, context: Any, image_bytes: bytes, user_prompt: str, preset_prompt: str = "") -> bool:
        provider = str(getattr(mod, "AI_SELFIE_PROVIDER", _env("AI_SELFIE_PROVIDER", "gemini")) or "").strip().lower()
        if provider not in _DIRECT_PROVIDERS or not _env("GEMINI_IMAGE_API_KEY"):
            return bool(await original(update, context, image_bytes, user_prompt, preset_prompt))

        chat_action = getattr(getattr(mod, "ChatAction", None), "UPLOAD_PHOTO", None)
        if chat_action is not None:
            with contextlib.suppress(Exception):
                await context.bot.send_chat_action(update.effective_chat.id, chat_action)
        if not image_bytes:
            await update.effective_message.reply_text("❌ Нет изображения для AI-селфи.")
            return False

        errors: list[str] = []
        try:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text(
                    "⏳ AI-селфи принято. Создаю сцену напрямую в Gemini и сохраняю ваше лицо без смешивания со знаменитостью…"
                )
            output: bytes | None = None
            try:
                output = await generate_direct(mod, image_bytes, user_prompt, preset_prompt)
            except Exception as exc:
                errors.append(str(exc))
                logger = getattr(mod, "log", None)
                if logger:
                    with contextlib.suppress(Exception):
                        logger.warning("Direct Gemini celebrity selfie failed: %s", exc)

            if not output and _flag("AI_SELFIE_GEMINI_FALLBACKS", True):
                comet = getattr(mod, "_run_comet_ai_selfie_bytes", None)
                if callable(comet) and str(getattr(mod, "COMET_API_KEY", "") or "").strip():
                    try:
                        output = await comet(image_bytes, user_prompt, preset_prompt)
                    except Exception as exc:
                        errors.append(f"Comet fallback: {exc}")
                openai_fallback = getattr(mod, "_run_openai_ai_selfie_fallback", None)
                openai_key = str(getattr(mod, "OPENAI_IMAGE_KEY", "") or "").strip()
                if not output and callable(openai_fallback) and openai_key and not openai_key.startswith("sk-or-"):
                    try:
                        output = await openai_fallback(image_bytes, user_prompt, preset_prompt)
                    except Exception as exc:
                        errors.append(f"OpenAI fallback: {exc}")

            if not output:
                raise RuntimeError("; ".join(errors[-4:]) or "image provider returned no result")

            bio = BytesIO(output)
            bio.name = "celebrity_selfie.png"
            caption = (
                "🤳 AI-селфи со звездой готово ✅\n"
                "Пометка: изображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
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
                    logger.exception("Celebrity selfie direct Gemini error: %s", exc)
            message = str(exc)[:1200]
            if "timeout" in message.lower() or "timed out" in message.lower():
                message = "Gemini не успел вернуть изображение. Повторите попытку с одним чётким портретом и коротким описанием сцены."
            await update.effective_message.reply_text(f"❌ AI-селфи не получилось. Причина: {message}")
            return False

    run._celebrity_selfie_direct_gemini = True  # type: ignore[attr-defined]
    run._celebrity_selfie_original = original  # type: ignore[attr-defined]
    mod._run_ai_selfie_image = run
    mod.AI_SELFIE_RUNTIME_VERSION = VERSION
    setattr(mod, _PATCH_FLAG, True)
    return True


def install_async() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED or not _flag("AI_SELFIE_DIRECT_GEMINI_ENABLED", True):
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable_rounds = 0
        for _ in range(3600):
            mod = _runtime_module()
            if mod is None:
                time.sleep(0.1)
                continue
            try:
                if patch_runtime(mod):
                    stable_rounds += 1
                    if stable_rounds >= 300:
                        return
                else:
                    stable_rounds = 0
            except Exception:
                stable_rounds = 0
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-celebrity-selfie-gemini", daemon=True).start()


__all__ = ["VERSION", "generate_direct", "patch_runtime", "install_async"]
