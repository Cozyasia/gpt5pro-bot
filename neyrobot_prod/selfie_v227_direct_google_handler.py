# -*- coding: utf-8 -*-
"""V227 hard route for Celebrity Selfie generation.

Generation callbacks are intercepted before every legacy selfie handler. This
module calls the official Gemini Developer API implementation directly and
accepts only GEMINI_IMAGE_API_KEY. No CometAPI route, alias key, or provider
fallback is reachable from this handler.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import threading
import time
from typing import Any

VERSION = "v227-selfie-hard-direct-google-handler-2026-07-28"
_HANDLER_FLAG = "_selfie_v227_direct_google_handler_bound"
_STARTED = False


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


def _log(message: str, *args: Any) -> None:
    runtime = _runtime()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.info(message, *args)
            return
    print(message % args if args else message, flush=True)


async def _google_generate(
    user_images: list[bytes],
    slug: str,
    scene: str,
    shot_mode: str,
    scene_image: bytes | None,
) -> bytes:
    from neyrobot_prod import selfie_v225_direct_gemini as direct

    key = _key()
    fp = _fingerprint(key)
    _log(
        "AI_SELFIE_V227_ROUTE provider=Google-Gemini-direct-only key_env=GEMINI_IMAGE_API_KEY key_fp=%s base_url=%s models=%s",
        fp,
        direct._base_url(),
        ",".join(direct._models()),
    )
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

    # The V225 direct implementation resolves this function at call time.
    direct._google_key = _key
    output = await direct._comet_generate(user_images, slug, scene, shot_mode, scene_image)

    runtime = _runtime()
    model = str(getattr(runtime, "AI_SELFIE_LAST_MODEL", "unknown") if runtime is not None else "unknown")
    image_size = str(getattr(runtime, "AI_SELFIE_LAST_IMAGE_SIZE", "unknown") if runtime is not None else "unknown")
    _log(
        "AI_SELFIE_V227_SUCCESS provider=Google-Gemini-direct-only model=%s image_size=%s key_fp=%s bytes=%s",
        model,
        image_size,
        fp,
        len(output or b""),
    )
    return output


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

    if not meta:
        await delivery._safe_text(message, "Сначала выберите страну и героя.")
        return False
    if not base._character_ready(runtime, slug):
        await delivery._safe_text(message, f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(runtime, slug)}.")
        return False
    if len(photos) != 3:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await delivery._safe_text(message, f"Нужны три фото пользователя. Сейчас получено {len(photos)}/3.")
        return False
    if shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON}:
        await message.reply_text("Сначала выберите тип кадра:", reply_markup=v215._shot_keyboard(runtime))
        return False
    if scene_mode not in {v215.SCENE_PRESET, v215.SCENE_DESCRIPTION, v215.SCENE_IMAGE} or not v219._scene_ready(context):
        await message.reply_text("Выберите способ задания сцены:", reply_markup=v215._scene_source_keyboard(runtime))
        return False

    if not _key():
        await delivery._safe_text(message, "❌ Прямой Google Gemini не настроен: отсутствует GEMINI_IMAGE_API_KEY. Другие ключи и CometAPI для этого режима отключены.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    refs_count = 10 if scene_mode == v215.SCENE_IMAGE else 9
    result = {"ok": False}

    async def action() -> bool:
        try:
            await delivery._safe_text(
                message,
                f"⏳ Создаю через прямой Google Gemini: {v215._shot_label(shot_mode)}, {v215._scene_mode_label(scene_mode)}. "
                f"Используется {refs_count} референсов: 3 фото пользователя + 3 кропа лица + 3 фото героя"
                + (" + фото сцены." if scene_mode == v215.SCENE_IMAGE else "."),
            )
            output = await _google_generate(photos, slug, scene_text, shot_mode, scene_image)
            if not output or len(output) < 1024:
                raise RuntimeError("Google Gemini returned an empty image")

            model = str(getattr(runtime, "AI_SELFIE_LAST_MODEL", "unknown"))
            result_name = "AI-селфи" if shot_mode == v215.SHOT_SELFIE else "Совместное AI-фото"
            caption = (
                f"🎭 {result_name} с персонажем «{meta['name']}» готово ✅\n"
                f"Режим: {v215._shot_label(shot_mode)} · {v215._scene_mode_label(scene_mode)}.\n"
                f"Маршрут: прямой Google Gemini API · модель: {model} · {refs_count} референсов. "
                "CometAPI для этого режима не используется. Изображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(
                message,
                output,
                caption,
                prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)),
            )
            result["ok"] = bool(delivered)
            context.user_data.pop("awaiting_ai_selfie_photo", None)
            context.user_data.pop("cs215_await_scene_image", None)
            await message.reply_text(
                "✅ Что сделать дальше? Три фото пользователя, герой, тип кадра и текущая сцена сохранены.",
                reply_markup=v215._continuation_keyboard(runtime, slug),
            )
            return True
        except Exception as exc:
            delivery._log_exception("V227 direct Google selfie failed", exc)
            await delivery._safe_text(
                message,
                f"❌ Прямой Google Gemini не создал изображение; средства не должны списываться. Причина: {type(exc).__name__}: {str(exc)[:700]}",
            )
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v227_google_direct",
        "remember_payload": {
            "character": slug,
            "scene": scene_text,
            "shot_mode": shot_mode,
            "scene_mode": scene_mode,
            "references": refs_count,
            "provider": "google_gemini_direct",
            "key_env": "GEMINI_IMAGE_API_KEY",
            "user_refs": 3,
            "user_face_refs": 3,
            "hero_refs": 3,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(
        update,
        context,
        int(user.id),
        "img",
        max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)),
        action,
        **kwargs,
    )
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
        if not preset:
            runtime = _runtime()
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(runtime))
            raise ApplicationHandlerStop
        context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
        context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
        context.user_data.pop("cs215_scene_image", None)
        await generate(update, context, context.user_data["cs215_scene_text"])
        raise ApplicationHandlerStop

    if data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if not v219._scene_ready(context):
            runtime = _runtime()
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(runtime))
        else:
            await generate(update, context, str(context.user_data.get("cs215_scene_text") or ""))
        raise ApplicationHandlerStop


def _is_app(value: Any) -> bool:
    return value is not None and callable(getattr(value, "add_handler", None)) and isinstance(getattr(value, "handlers", None), dict)


def bind_application(app: Any) -> bool:
    if not _is_app(app) or getattr(app, _HANDLER_FLAG, False):
        return bool(_is_app(app))
    from telegram.ext import CallbackQueryHandler

    app.add_handler(
        CallbackQueryHandler(
            generation_callback,
            pattern=r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)",
        ),
        group=-10000,
    )
    setattr(app, _HANDLER_FLAG, True)
    return True


def bind_runtime_apps() -> int:
    runtime = _runtime()
    if runtime is None:
        return 0
    count = 0
    seen: set[int] = set()
    for value in vars(runtime).values():
        if id(value) in seen:
            continue
        seen.add(id(value))
        with contextlib.suppress(Exception):
            if bind_application(value):
                count += 1
    return count


def patch_runtime() -> bool:
    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v227-hard-handler-direct-google-only"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_ACTIVE_KEY_FINGERPRINT = _fingerprint(_key())
        runtime.AI_SELFIE_CONFIGURED = bool(_key())
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3
    bind_runtime_apps()
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
                _log("V227 hard direct Google handler patch failed: %r", exc)
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v227-hard-google-handler").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "generate", "generation_callback", "bind_application", "patch_runtime", "install_async", "install"]
