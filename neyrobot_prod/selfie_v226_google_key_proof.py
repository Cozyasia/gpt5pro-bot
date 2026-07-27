# -*- coding: utf-8 -*-
"""V226 proof layer for the direct Google Gemini selfie route.

Only GEMINI_IMAGE_API_KEY is accepted. The route is hard-wired to the V225
Google implementation and cannot fall back to CometAPI or key aliases.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import threading
import time
from typing import Any

from neyrobot_prod import selfie_v221_identity_scene_lock as strict
from neyrobot_prod import selfie_v225_direct_gemini as direct

VERSION = "v226-selfie-direct-google-key-proof-fixed-2026-07-28"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _single_google_key() -> str:
    return (os.environ.get("GEMINI_IMAGE_API_KEY") or "").strip()


def _fingerprint(key: str) -> str:
    if not key:
        return "missing"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _log(message: str, *args: Any) -> None:
    runtime = _runtime()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.info(message, *args)
            return
    with contextlib.suppress(Exception):
        print(message % args if args else message, flush=True)


async def _direct_generate(user_images: list[bytes], slug: str, scene: str, shot_mode: str, scene_image: bytes | None) -> bytes:
    key = _single_google_key()
    fp = _fingerprint(key)
    models = direct._models()
    base_url = direct._base_url()
    _log(
        "AI_SELFIE_ROUTE provider=Google-Gemini-direct-only key_env=GEMINI_IMAGE_API_KEY key_fp=%s models=%s base_url=%s",
        fp,
        ",".join(models),
        base_url,
    )
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing; all aliases and Comet fallback are disabled")

    runtime = _runtime()
    if runtime is not None:
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_ACTIVE_KEY_FINGERPRINT = fp
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_CONFIGURED = True

    # Force the direct implementation to read only this exact variable.
    direct._google_key = _single_google_key
    output = await direct._comet_generate(user_images, slug, scene, shot_mode, scene_image)

    runtime = _runtime()
    model = str(getattr(runtime, "AI_SELFIE_LAST_MODEL", "unknown") if runtime is not None else "unknown")
    image_size = str(getattr(runtime, "AI_SELFIE_LAST_IMAGE_SIZE", "unknown") if runtime is not None else "unknown")
    _log(
        "AI_SELFIE_SUCCESS provider=Google-Gemini-direct-only model=%s image_size=%s key_fp=%s bytes=%s",
        model,
        image_size,
        fp,
        len(output or b""),
    )
    return output


def patch_runtime() -> bool:
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v220_runtime_marker as v220

    # Make every legacy owner point to the direct Google stack.
    direct._google_key = _single_google_key
    strict._google_key = _single_google_key
    strict._models = direct._models
    strict._base_url = direct._base_url
    strict._prompt = direct._prompt
    strict._prepare_stack = direct._prepare_stack
    strict._comet_generate = _direct_generate
    strict.VERSION = VERSION

    v219._prompt = direct._prompt
    v219._prepare_stack = direct._prepare_stack
    v219._comet_generate = _direct_generate
    v219.VERSION = VERSION
    v218.VERSION = VERSION
    v220.VERSION = VERSION

    runtime = _runtime()
    key = _single_google_key()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v226-direct-google-only-3-user-3-face-3-hero"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_ACTIVE_KEY_FINGERPRINT = _fingerprint(key)
        runtime.AI_SELFIE_CONFIGURED = bool(key)
        runtime.AI_SELFIE_MODELS = ",".join(direct._models())
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
                _log("V226 Google key proof patch failed: %r", exc)
            time.sleep(0.05)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v226-google-key-proof-fixed").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "_single_google_key", "_fingerprint", "_direct_generate", "patch_runtime", "install_async", "install"]
