# -*- coding: utf-8 -*-
"""Deterministic owner for the strict three-photo plus face-anchor selfie pipeline.

Legacy V218/V219 workers re-apply their own runtime patches. This layer wraps
both historical patch entry points and always finalizes them with the current
strict generator from ``selfie_v221_identity_scene_lock``.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any, Callable

from neyrobot_prod import selfie_v221_identity_scene_lock as strict

VERSION = "v224-selfie-user-face-anchor-scene-lock-2026-07-27"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _finalize() -> bool:
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v220_runtime_marker as v220

    v219._prompt = strict._prompt
    v219._prepare_stack = strict._prepare_stack
    v219._comet_generate = strict._comet_generate
    v219.VERSION = VERSION
    v218.VERSION = VERSION
    v220.VERSION = VERSION

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v224-scene-first-3-user-3-face-3-hero"
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        runtime.AI_SELFIE_SCENE_REFERENCE_POSITION = 1
    return True


def _wrap(module: Any, attr: str, marker: str) -> None:
    current = getattr(module, attr, None)
    if not callable(current) or getattr(current, marker, False):
        return
    original: Callable[..., Any] = current

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        _finalize()
        return result

    setattr(wrapped, marker, True)
    setattr(wrapped, "_v224_original", original)
    setattr(module, attr, wrapped)


def patch_runtime() -> bool:
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    _wrap(v219, "patch_runtime", "_v224_wrapped_v219")
    _wrap(v218, "patch_runtime", "_v224_wrapped_v218")
    _finalize()
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
                runtime = _runtime()
                logger = getattr(runtime, "log", None) if runtime is not None else None
                with contextlib.suppress(Exception):
                    logger.exception("V224 deterministic selfie owner failed: %r", exc)
            time.sleep(0.25)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v224-deterministic-owner").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "patch_runtime", "install_async", "install"]