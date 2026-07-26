# -*- coding: utf-8 -*-
"""V214 post-result reuse controls for Celebrity Selfie.

After a successful generation, keep the current two user photos and selected
hero in PTB user_data and show three explicit continuation actions:

* choose another scene with the same hero and same user photos;
* choose another hero with the same user photos;
* replace the user photos and begin again.

The module preserves V213 identity generation, V211 reliable delivery and V210's
duplicate-click guard. Each new generation still passes through the normal paid
runner and is billed independently only after successful delivery.
"""
from __future__ import annotations

import contextlib
import sys
from typing import Any

VERSION = "v214-selfie-reuse-controls-2026-07-26"


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _continuation_keyboard(runtime: Any, slug: str):
    from neyrobot_prod import celebrity_selfie as base

    meta = base.CHARACTERS.get(slug) or {}
    hero_name = str(meta.get("name") or "текущий герой")
    return runtime.InlineKeyboardMarkup([
        [runtime.InlineKeyboardButton(
            f"🎬 Другая сцена · {hero_name}",
            callback_data=f"cs201:character:{slug}",
        )],
        [runtime.InlineKeyboardButton(
            "⭐ Выбрать другого героя",
            callback_data="cs201:characters",
        )],
        [runtime.InlineKeyboardButton(
            "📸 Сменить фотографии пользователя",
            callback_data="cs201:photo",
        )],
        [runtime.InlineKeyboardButton(
            "⬅️ В меню AI-селфи",
            callback_data="cs201:open",
        )],
    ])


def _preserve_generation_state(runtime: Any, context: Any, user_id: int, slug: str) -> None:
    """Retain exactly the reusable inputs while removing stale transient flags."""
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

    for key in (
        "cs201_scene",
        "cs201_wait_custom_scene",
        "awaiting_ai_selfie_photo",
        "awaiting_ai_selfie_prompt",
        "ai_selfie_preset_prompt",
    ):
        context.user_data.pop(key, None)


async def generate(update: Any, context: Any, scene: str) -> bool:
    """Generate once, deliver reliably, then expose reuse actions."""
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

    if not meta:
        await v211._safe_text(message, "Сначала выберите страну и героя.")
        return False
    if not base._character_ready(runtime, slug):
        await v211._safe_text(
            message,
            f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(runtime, slug)}.",
        )
        return False
    if len(photos) != 2:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await v211._safe_text(
            message,
            "Нужны два селфи пользователя. Загрузите селфи 1/2 и селфи 2/2 заново.",
        )
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await v211._safe_text(
            message,
            "❌ Платёжный guard генераций не найден. Средства не списаны.",
        )
        return False

    result = {"ok": False}

    async def action() -> bool:
        output: bytes | None = None
        try:
            await v211._safe_text(
                message,
                "⏳ Создаю AI-селфи: 2 фото пользователя + 2 крупных портрета лица + 3 JPEG героя. "
                "Обычно это занимает 1–3 минуты.",
            )
            output = await v208._comet_generate(photos, slug, str(scene or ""))
            if not output or len(output) < 1024:
                raise RuntimeError("provider returned an empty image")

            caption = (
                f"🤳 AI-селфи с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут: CometAPI / Gemini, 7 референсов с усилением личности пользователя. "
                "Изображение сгенерировано ИИ."
            )
            prefer_document = bool(
                getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)
            )
            delivered = await v211._deliver(
                message,
                output,
                caption,
                prefer_document=prefer_document,
            )
            result["ok"] = bool(delivered)

            _preserve_generation_state(
                runtime,
                context,
                int(user.id),
                slug,
            )
            await message.reply_text(
                "✅ Что сделать дальше? Текущие фотографии пользователя и выбранный герой сохранены.",
                reply_markup=_continuation_keyboard(runtime, slug),
                write_timeout=90.0,
                read_timeout=90.0,
                connect_timeout=30.0,
                pool_timeout=30.0,
            )
            return True
        except Exception as exc:
            v211._log_exception("V214 selfie action failed", exc)
            recovery = (
                v211._save_recovery_copy(
                    runtime,
                    int(user.id),
                    v211._jpeg(output or b"", max_side=1800, quality=91),
                )
                if output
                else None
            )
            if recovery is not None:
                await v211._safe_text(
                    message,
                    "❌ Изображение было создано, но Telegram не принял файл после повторных попыток. "
                    "Средства не должны списываться. Результат сохранён на сервере для диагностики.",
                )
            else:
                detail = f"{type(exc).__name__}: {str(exc)[:700]}"
                await v211._safe_text(
                    message,
                    "❌ AI-селфи не создано; средства не должны списываться. "
                    f"Техническая причина: {detail}",
                )
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v214",
        "remember_payload": {
            "character": slug,
            "scene": str(scene or ""),
            "references": 7,
            "provider": "comet",
            "identity_lock": True,
            "reuse_controls": True,
        },
    }
    if v211._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True

    await runner(
        update,
        context,
        int(user.id),
        "img",
        max(
            0.0,
            float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20),
        ),
        action,
        **kwargs,
    )
    return bool(result["ok"])


def patch_runtime() -> bool:
    """Replace only final generation UX while retaining the V213 provider route."""
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v210_generation_guard as v210
    from neyrobot_prod import selfie_v211_delivery as v211
    from neyrobot_prod import selfie_v213_user_identity_lock as v213

    v208._generate = generate
    v211.generate = generate

    for module in (
        v208,
        v209,
        v210,
        v211,
        v213,
        generator_v204,
        commands_v206,
        runtime_v207,
        storage_v205,
    ):
        module.VERSION = VERSION

    runtime = _runtime_module()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = (
            "v214-seven-reference-user-identity-reuse-controls"
        )
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_REUSE_CONTROLS = True
    return True


def install_async() -> None:
    patch_runtime()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "generate",
    "patch_runtime",
    "install_async",
    "install",
]
