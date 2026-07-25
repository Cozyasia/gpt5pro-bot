# -*- coding: utf-8 -*-
"""Celebrity Selfie V203: strict four-reference Gemini generation.

This overlay owns the final character/scene stage. It preserves the existing
billing guard, sends exactly four images to Gemini (user + three character
references), disables silent Comet fallback for configured characters and keeps
references on the Render persistent disk.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

VERSION = "v203-selfie-four-reference-gemini-2026-07-25"
_INSTALLED = False
_BUILDER_HOOKED = False
_WORKER_STARTED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".v203_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def storage_root(mod: Any) -> Path:
    """Prefer the Render persistent disk and migrate old source-tree refs."""
    configured = (os.environ.get("CELEBRITY_SELFIE_DATA_DIR") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path("/data/celebrity_selfie"))
    db_path = Path(str(getattr(mod, "DB_PATH", "/data/subs.db") or "/data/subs.db")).resolve()
    candidates.append(db_path.parent / "celebrity_selfie")
    candidates.append(Path("/tmp/celebrity_selfie"))
    chosen = next((path for path in candidates if _writable(path)), Path("/tmp/celebrity_selfie"))

    # Best-effort migration while the previous deployment filesystem is available.
    legacy_candidates = [
        Path.cwd() / "celebrity_selfie",
        Path("/opt/render/project/src/celebrity_selfie"),
    ]
    for legacy in legacy_candidates:
        if chosen == legacy or not legacy.exists():
            continue
        legacy_chars = legacy / "characters"
        target_chars = chosen / "characters"
        with contextlib.suppress(Exception):
            target_chars.mkdir(parents=True, exist_ok=True)
            for source in legacy_chars.rglob("*") if legacy_chars.exists() else ():
                if source.is_file() and source.suffix.lower() in {".jpg", ".jpeg"}:
                    relative = source.relative_to(legacy_chars)
                    target = target_chars / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists() or target.stat().st_size < 1024:
                        shutil.copy2(source, target)
    return chosen


def payload(prompt: str, images: list[tuple[str, str]], *, compatibility: bool) -> dict[str, Any]:
    """Build the official models:generateContent REST request with four images."""
    labels = (
        "REFERENCE 1 — USER SELFIE. Preserve this person's identity exactly.",
        "REFERENCE 2 — CHARACTER PHOTO A. This is the selected second person.",
        "REFERENCE 3 — CHARACTER PHOTO B. Same second person as reference 2.",
        "REFERENCE 4 — CHARACTER PHOTO C. Same second person as references 2 and 3.",
    )
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for index, (image_b64, mime) in enumerate(images):
        parts.append({"text": labels[index] if index < len(labels) else f"REFERENCE {index + 1}."})
        # The raw generateContent REST examples use inline_data/mime_type.
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})

    generation_config: dict[str, Any] = {
        "responseModalities": ["TEXT", "IMAGE"] if compatibility else ["IMAGE"],
    }
    if not compatibility:
        from neyrobot_prod import celebrity_selfie as base
        generation_config["responseFormat"] = {
            "image": {
                "aspectRatio": base._aspect_ratio(),
                "imageSize": base._image_size(),
            }
        }
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }


def identity_prompt(character_name: str = "the selected second person") -> str:
    return (
        "STRICT IDENTITY COMPOSITION RULES. Create exactly two people. "
        "Reference 1 is the user and must determine only the user's face, hairline, eye shape, nose, mouth, age, skin texture and beard. "
        f"References 2, 3 and 4 are three photos of the same second person, {character_name}; use all three together to reconstruct only that person's identity. "
        "Do not invent a generic substitute for either person. Do not merge, average, swap, beautify, rejuvenate or duplicate faces. "
        "The second person's facial proportions, eyes, nose, mouth, jaw, hair and age must remain recognizably consistent with references 2–4. "
        "The user must remain recognizably consistent with reference 1. Place both people naturally in one arm's-length smartphone selfie. "
        "Match perspective, lens distortion, scale, lighting and skin texture. Correct hands and anatomy. No text, logo, watermark or UI. "
        "This is a fictional AI-generated fan scene and not evidence of a real meeting or endorsement."
    )


def prompt(mod: Any, user_prompt: str, preset_prompt: str = "", character_name: str = "") -> str:
    scene = (user_prompt or preset_prompt or "realistic smartphone selfie").strip()
    return (
        "Create one photorealistic vertical smartphone selfie, not a portrait collage. "
        f"SCENE: {scene[:1400]}. "
        f"{identity_prompt(character_name)}"
    )


async def _send_direct_result(
    mod: Any,
    update: Any,
    context: Any,
    *,
    image: bytes,
    slug: str,
    scene_text: str,
) -> bool:
    from neyrobot_prod import celebrity_selfie as base

    meta = base.CHARACTERS.get(slug) or {}
    character_name = str(meta.get("name") or slug)
    try:
        await update.effective_message.reply_text(
            "⏳ Создаю AI-селфи через Gemini по четырём изображениям: "
            "ваше селфи + 3 референса выбранного героя. Comet для этого режима отключён."
        )
        output = await base.generate_direct(
            mod,
            image,
            f"Фикционное AI-селфи пользователя с {character_name}. Сцена: {scene_text}. Формат {base._aspect_ratio()}.",
            "",
            character_slug=slug,
        )
        if not output or len(output) < 1024:
            raise RuntimeError("Gemini вернул пустое изображение")

        bio = BytesIO(output)
        bio.name = "celebrity_selfie_v203.png"
        caption = (
            f"🤳 AI-селфи с персонажем «{character_name}» готово ✅\n"
            "Создано Gemini по четырём референсам. Изображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
        )
        if bool(getattr(mod, "AI_SELFIE_SEND_AS_DOCUMENT", True)):
            input_file = getattr(mod, "InputFile", None)
            await update.effective_message.reply_document(
                input_file(bio) if callable(input_file) else bio,
                caption=caption,
            )
        else:
            await update.effective_message.reply_photo(photo=output, caption=caption)
        return True
    except Exception as exc:
        logger = getattr(mod, "log", None)
        if logger:
            with contextlib.suppress(Exception):
                logger.exception("Celebrity Selfie V203 generation failed: %s", exc)
        await update.effective_message.reply_text(
            "❌ Gemini не создал корректное четырёхреференсное селфи. "
            f"Средства за неуспешный результат не должны списываться. Причина: {str(exc)[:900]}"
        )
        return False


async def generate(mod: Any, update: Any, context: Any, scene_text: str) -> None:
    """Own the final character/scene stage and bypass legacy Comet entirely."""
    from neyrobot_prod import celebrity_selfie as base

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    if not meta:
        await update.effective_message.reply_text(
            "Сначала выберите героя.",
            reply_markup=base._character_kb(mod),
        )
        return
    if not base._character_ready(mod, slug):
        await update.effective_message.reply_text(
            f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(mod, slug)}.",
            reply_markup=base._character_kb(mod),
        )
        return
    if not (os.environ.get("GEMINI_IMAGE_API_KEY") or "").strip():
        await update.effective_message.reply_text(
            "❌ GEMINI_IMAGE_API_KEY не найден. Для героя с тремя референсами Comet намеренно не используется, "
            "чтобы не выдавать случайное лицо. Добавьте ключ в Render и повторите после деплоя."
        )
        return

    image = base._cached_photo(mod, update.effective_user.id)
    if not image:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await update.effective_message.reply_text(
            "Селфи пользователя не найдено. Пришлите его ещё раз.",
            reply_markup=base._main_kb(mod),
        )
        return

    context.user_data["cs201_character"] = slug
    context.user_data["cs201_scene"] = scene_text
    paid_runner = getattr(mod, "_try_pay_then_do", None)
    if not callable(paid_runner):
        await update.effective_message.reply_text(
            "❌ Платёжный guard генераций не найден. Запуск остановлен, чтобы не обходить биллинг."
        )
        return

    async def action() -> bool:
        return await _send_direct_result(
            mod,
            update,
            context,
            image=image,
            slug=slug,
            scene_text=scene_text,
        )

    cost = max(0.0, float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20))
    await paid_runner(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        action,
        remember_kind="celebrity_selfie_v203",
        remember_payload={
            "character": slug,
            "scene": scene_text,
            "references": 4,
            "provider": "gemini-direct",
        },
    )


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    mod = _runtime_module()
    try:
        if mod is None:
            return
        current_generate = getattr(base, "_generate", None)
        lines = [
            "🤳 Celebrity Selfie diagnostic",
            f"version={VERSION}",
            f"route={'v203-direct-paid' if getattr(current_generate, '_selfie_v203', False) else 'legacy'}",
            f"gemini_key={'on' if bool((os.environ.get('GEMINI_IMAGE_API_KEY') or '').strip()) else 'off'}",
            f"model_primary={(os.environ.get('GEMINI_IMAGE_MODEL') or 'gemini-3-pro-image').strip()}",
            f"model_fallback={(os.environ.get('GEMINI_IMAGE_FALLBACK_MODEL') or 'gemini-3.1-flash-image').strip()}",
            f"storage={base._storage_root(mod)}",
            f"roman_abramovich={base._character_status(mod, 'roman_abramovich')}",
            f"ready={'on' if base._character_ready(mod, 'roman_abramovich') else 'off'}",
            "comet_character_fallback=off",
            "payload_fields=inline_data/mime_type",
        ]
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def patch() -> bool:
    from neyrobot_prod import celebrity_selfie as base

    os.environ.setdefault("CELEBRITY_SELFIE_DATA_DIR", "/data/celebrity_selfie")
    base._storage_root = storage_root
    base._payload = payload
    base._identity_guard = identity_prompt
    base._prompt = prompt
    generate._selfie_v203 = True
    base._generate = generate

    mod = _runtime_module()
    if mod is not None:
        mod.CELEBRITY_SELFIE_VERSION = VERSION
        mod.AI_SELFIE_RUNTIME_VERSION = VERSION
        mod.CELEBRITY_SELFIE_ROUTE = "v203-direct-paid"
    return True


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return False

    flag = "_celebrity_selfie_v203_builder"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return True

    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, flag, False):
            # Higher priority than V201's /diag_selfie handler.
            app.add_handler(CommandHandler("diag_selfie", diagnostic), group=-60)
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
        # main.py defines billing/runtime symbols after secret_loader imports us.
        # Keep the overlay last during bootstrap and publish V203 component version.
        stable = 0
        for _ in range(3600):
            try:
                if patch():
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

    threading.Thread(
        target=worker,
        name="neyrobot-celebrity-selfie-v203",
        daemon=True,
    ).start()


def install() -> None:
    global _INSTALLED
    install_async()
    _INSTALLED = True


__all__ = [
    "VERSION",
    "storage_root",
    "payload",
    "identity_prompt",
    "prompt",
    "generate",
    "diagnostic",
    "patch",
    "install_builder_hook",
    "install_async",
    "install",
]
