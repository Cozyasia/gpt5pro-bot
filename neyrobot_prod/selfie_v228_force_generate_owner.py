# -*- coding: utf-8 -*-
"""V228 final owner for Celebrity Selfie generation.

The legacy V219 callback handler is already bound to Telegram at startup. Instead
of relying on an additional callback handler, this layer replaces the global
``generate`` function used by that bound callback and every known alias with the
V227 direct-Google implementation. It also replaces the legacy provider function.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

from neyrobot_prod import selfie_v227_direct_google_handler as direct

VERSION = "v228-selfie-force-direct-google-owner-2026-07-28"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v220_runtime_marker as v220

    # Critical fix: the already-bound V219 callback resolves these globals at call time.
    v219.generate = direct.generate
    v219._comet_generate = direct._google_generate

    # Replace every known generation alias used by older menu layers.
    base._generate = direct.generate
    v208._generate = direct.generate
    v215.generate = direct.generate
    v215._comet_generate = direct._google_generate
    v217.generate = direct.generate

    # Keep all visible runtime markers consistent with the actual route.
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
        runtime.CELEBRITY_SELFIE_ROUTE = "v228-force-v219-generate-to-direct-google"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_ACTIVE_KEY_FINGERPRINT = direct._fingerprint(direct._key())
        runtime.AI_SELFIE_CONFIGURED = bool(direct._key())
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3
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
                    logger.exception("V228 direct Google owner failed: %r", exc)
            time.sleep(0.05)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v228-force-direct-google").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "patch_runtime", "install_async", "install"]
