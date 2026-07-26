# -*- coding: utf-8 -*-
"""V211 reliable delivery for the five-reference Celebrity Selfie flow.

V210 fixed generation dispatch and duplicate scene taps. Production testing then
showed a Telegram ``TimedOut`` after the provider had spent most of a minute
rendering the image. The V208 action treated generation and Telegram upload as
one operation, so a slow document upload discarded an otherwise valid result.

V211 keeps provider generation and result delivery separate, compresses the
result to a Telegram-friendly JPEG, retries uploads with explicit long network
timeouts, and asks the paid runner to suppress its second generic error message.
Credits remain chargeable only after a result has actually reached the chat.
"""
from __future__ import annotations

import contextlib
import inspect
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any

VERSION = "v211-selfie-delivery-retry-2026-07-26"
_DELIVERY_WRITE_TIMEOUT = 240.0
_DELIVERY_READ_TIMEOUT = 240.0
_DELIVERY_CONNECT_TIMEOUT = 40.0
_DELIVERY_POOL_TIMEOUT = 40.0


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _log_exception(label: str, exc: BaseException) -> None:
    runtime = _runtime_module()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.exception("%s: %s", label, exc)
            return
    print(f"[neyrobot-prod] {label}: {type(exc).__name__}: {exc}")


async def _safe_text(message: Any, text: str) -> None:
    if message is None:
        return
    try:
        await message.reply_text(
            text,
            write_timeout=90.0,
            read_timeout=90.0,
            connect_timeout=30.0,
            pool_timeout=30.0,
        )
    except Exception as exc:
        _log_exception("V211 status message failed", exc)


def _jpeg(raw: bytes, *, max_side: int, quality: int) -> bytes:
    """Return a compact RGB JPEG; preserve the original bytes if Pillow is absent."""
    data = bytes(raw or b"")
    if not data:
        return data
    try:
        from PIL import Image, ImageOps

        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        if max_side > 0 and max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.LANCZOS)
        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=max(72, min(95, int(quality))),
            optimize=True,
            progressive=True,
        )
        encoded = output.getvalue()
        return encoded if len(encoded) > 1024 else data
    except Exception as exc:
        _log_exception("V211 result compression failed", exc)
        return data


def _save_recovery_copy(runtime: Any, user_id: int, raw: bytes) -> Path | None:
    """Keep a generated-but-undelivered image on Persistent Disk for diagnosis."""
    candidates = [Path("/data/celebrity_selfie/results")]
    db_path = Path(str(getattr(runtime, "DB_PATH", "/data/subs.db") or "/data/subs.db"))
    candidates.append(db_path.parent / "celebrity_selfie" / "results")
    candidates.append(Path("/tmp/celebrity_selfie/results"))
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            path = root / f"{int(user_id)}-{int(time.time())}.jpg"
            path.write_bytes(raw)
            return path
        except Exception:
            continue
    return None


async def _send_document(message: Any, payload: bytes, caption: str, *, timeout: float) -> None:
    from telegram import InputFile

    bio = BytesIO(payload)
    bio.name = "celebrity_selfie.jpg"
    await message.reply_document(
        document=InputFile(bio, filename=bio.name),
        caption=caption,
        write_timeout=timeout,
        read_timeout=_DELIVERY_READ_TIMEOUT,
        connect_timeout=_DELIVERY_CONNECT_TIMEOUT,
        pool_timeout=_DELIVERY_POOL_TIMEOUT,
    )


async def _send_photo(message: Any, payload: bytes, caption: str, *, timeout: float) -> None:
    from telegram import InputFile

    bio = BytesIO(payload)
    bio.name = "celebrity_selfie.jpg"
    await message.reply_photo(
        photo=InputFile(bio, filename=bio.name),
        caption=caption,
        write_timeout=timeout,
        read_timeout=_DELIVERY_READ_TIMEOUT,
        connect_timeout=_DELIVERY_CONNECT_TIMEOUT,
        pool_timeout=_DELIVERY_POOL_TIMEOUT,
    )


async def _deliver(message: Any, raw: bytes, caption: str, *, prefer_document: bool) -> bytes:
    """Retry only Telegram delivery; never regenerate an already-created image."""
    primary = _jpeg(raw, max_side=1800, quality=91)
    compact = _jpeg(raw, max_side=1280, quality=86)
    attempts = (
        ("document" if prefer_document else "photo", primary, _DELIVERY_WRITE_TIMEOUT),
        ("photo" if prefer_document else "document", primary, _DELIVERY_WRITE_TIMEOUT),
        ("photo", compact, 300.0),
    )
    errors: list[str] = []
    for index, (kind, payload, timeout) in enumerate(attempts, 1):
        try:
            if kind == "document":
                await _send_document(message, payload, caption, timeout=timeout)
            else:
                await _send_photo(message, payload, caption, timeout=timeout)
            return payload
        except Exception as exc:
            errors.append(f"attempt {index} {kind}: {type(exc).__name__}: {exc}")
            _log_exception(f"V211 Telegram delivery attempt {index} failed", exc)
            if index < len(attempts):
                import asyncio
                await asyncio.sleep(float(index * 2))
    raise RuntimeError("Telegram delivery failed: " + " | ".join(errors[-3:]))


def _runner_accepts_silent_failure(runner: Any) -> bool:
    try:
        signature = inspect.signature(runner)
        if "silent_failure" in signature.parameters:
            return True
        return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    except Exception:
        return True


async def generate(update: Any, context: Any, scene: str) -> bool:
    """Generate once, deliver with retries, and debit only after successful delivery."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208

    runtime = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    photos = v208._photos(context)
    if not meta:
        await _safe_text(message, "Сначала выберите страну и героя.")
        return False
    if not base._character_ready(runtime, slug):
        await _safe_text(message, f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(runtime, slug)}.")
        return False
    if len(photos) != 2:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await _safe_text(message, "Нужны два селфи пользователя. Загрузите селфи 1/2 и селфи 2/2 заново.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await _safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    result = {"ok": False}

    async def action() -> bool:
        output: bytes | None = None
        try:
            await _safe_text(message, "⏳ Создаю AI-селфи: 2 селфи пользователя + 3 JPEG героя. Обычно это занимает 1–3 минуты.")
            output = await v208._comet_generate(photos, slug, str(scene or ""))
            if not output or len(output) < 1024:
                raise RuntimeError("provider returned an empty image")

            caption = (
                f"🤳 AI-селфи с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут: CometAPI / Gemini, 5 референсов. Изображение сгенерировано ИИ."
            )
            prefer_document = bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True))
            delivered = await _deliver(message, output, caption, prefer_document=prefer_document)
            result["ok"] = bool(delivered)

            # Never retain user photos after a completed request.
            v208._clear(context, keep_photos=False)
            setter = getattr(runtime, "_set_mode_clean", None)
            if callable(setter):
                with contextlib.suppress(Exception):
                    setter(int(user.id), "Развлечения", "")
            return True
        except Exception as exc:
            _log_exception("V211 selfie action failed", exc)
            recovery = _save_recovery_copy(runtime, int(user.id), _jpeg(output or b"", max_side=1800, quality=91)) if output else None
            if recovery is not None:
                await _safe_text(
                    message,
                    "❌ Изображение было создано, но Telegram не принял файл после повторных попыток. "
                    "Средства не должны списываться. Результат сохранён на сервере для диагностики.",
                )
            else:
                detail = f"{type(exc).__name__}: {str(exc)[:700]}"
                await _safe_text(
                    message,
                    "❌ AI-селфи не создано; средства не должны списываться. "
                    f"Техническая причина: {detail}",
                )
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v211",
        "remember_payload": {
            "character": slug,
            "scene": str(scene or ""),
            "references": 5,
            "provider": "comet",
            "delivery_retry": True,
        },
    }
    if _runner_accepts_silent_failure(runner):
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


def patch_runtime() -> bool:
    """Install V211 under V210's signature/duplicate-click adapter."""
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v210_generation_guard as v210

    # Do not let a stale 60-second Render value terminate a valid provider request.
    try:
        configured = float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300") or 300)
    except Exception:
        configured = 300.0
    os.environ["COMET_SELFIE_TIMEOUT_S"] = str(int(max(300.0, configured)))

    v208._generate = generate
    v208.VERSION = VERSION
    v209.VERSION = VERSION
    v210.VERSION = VERSION
    generator_v204.VERSION = VERSION
    commands_v206.VERSION = VERSION
    runtime_v207.VERSION = VERSION
    storage_v205.VERSION = VERSION

    runtime = _runtime_module()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v211-comet-five-reference-delivery-retry"
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
    return True


def install_async() -> None:
    patch_runtime()


def install() -> None:
    install_async()


__all__ = ["VERSION", "generate", "patch_runtime", "install_async", "install"]
