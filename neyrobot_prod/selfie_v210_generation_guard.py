# -*- coding: utf-8 -*-
"""V210 generation dispatch and duplicate-click guard for Celebrity Selfie.

V208's public scene callbacks use the historical four-argument generator
contract ``(runtime, update, context, scene)``, while its new implementation
accepts ``(update, context, scene)``. V210 provides one compatibility adapter,
keeps that adapter pinned after legacy startup workers, and prevents repeated
scene taps from starting duplicate billable jobs.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v210-selfie-generation-guard-2026-07-26"
_BUSY_KEY = "cs210_generation_started_at"
_BUSY_TTL_SECONDS = 15 * 60
_STARTED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _decode_generate_args(args: tuple[Any, ...]) -> tuple[Any, Any, str]:
    if len(args) == 4:
        _runtime, update, context, scene = args
    elif len(args) == 3:
        update, context, scene = args
    else:
        raise TypeError(
            "Celebrity Selfie generator expects (update, context, scene) or "
            "(runtime, update, context, scene)"
        )
    return update, context, str(scene or "").strip()


def _acquire_generation(context: Any) -> bool:
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        return True
    now = time.time()
    try:
        started = float(user_data.get(_BUSY_KEY, 0.0) or 0.0)
    except (TypeError, ValueError):
        started = 0.0
    if started and now - started < _BUSY_TTL_SECONDS:
        return False
    user_data[_BUSY_KEY] = now
    return True


def _release_generation(context: Any) -> None:
    user_data = getattr(context, "user_data", None)
    if isinstance(user_data, dict):
        user_data.pop(_BUSY_KEY, None)


def _log_exception(label: str, exc: Exception) -> None:
    runtime = _runtime_module()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.exception("%s: %s", label, exc)
            return
    print(f"[neyrobot-prod] {label}: {type(exc).__name__}: {exc}")


async def generate(*args: Any) -> bool:
    """Accept both legacy and V208 signatures and serialize each user's job."""
    update, context, scene = _decode_generate_args(args)
    message = getattr(update, "effective_message", None)

    if not _acquire_generation(context):
        if message is not None:
            with contextlib.suppress(Exception):
                await message.reply_text(
                    "⏳ AI-селфи уже создаётся. Не нажимайте сцену повторно — "
                    "готовый результат появится в этом чате."
                )
        return False

    try:
        from neyrobot_prod import selfie_v208_overlay as v208

        return bool(await v208._generate(update, context, scene))
    except Exception as exc:
        _log_exception("V210 selfie generation dispatch failed", exc)
        if message is not None:
            with contextlib.suppress(Exception):
                await message.reply_text(
                    "❌ Не удалось запустить создание AI-селфи. "
                    "Средства не должны списываться. Попробуйте выбрать сцену ещё раз."
                )
        return False
    finally:
        _release_generation(context)


def patch_runtime() -> bool:
    """Pin the compatible generator after every historical selfie layer."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209

    # Already-started workers resolve these module globals on every iteration.
    # Replacing them stops V204/V208/V209 from restoring the incompatible target.
    generator_v204.patch = lambda: True
    v208.patch = lambda: True
    v209.patch_runtime = lambda: True
    runtime_v207.patch_runtime = lambda: True

    base.callback = v208._public_callback
    base.media_entry = v208._public_media
    base.text_entry = v208._public_text
    base._generate = generate
    generator_v204.generate = generate

    v208.VERSION = VERSION
    v209.VERSION = VERSION
    generator_v204.VERSION = VERSION
    commands_v206.VERSION = VERSION
    runtime_v207.VERSION = VERSION
    storage_v205.VERSION = VERSION

    runtime = _runtime_module()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v210-comet-five-reference-guarded"
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
        # Keep the adapter pinned while all historical startup workers settle.
        for _ in range(7200):
            try:
                patch_runtime()
            except Exception as exc:
                _log_exception("V210 selfie pin failed", exc)
            time.sleep(0.1)

    threading.Thread(
        target=worker,
        daemon=True,
        name="neyrobot-selfie-v210-generation-guard",
    ).start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "generate",
    "patch_runtime",
    "install_async",
    "install",
]
