# -*- coding: utf-8 -*-
"""V244: final runtime lock for the proven V243 selfie pipeline.

This release does not change identity transfer, expression, composition or detail
processing. Its only purpose is to guarantee that V243 is the last owner at the
actual ApplicationBuilder/generation boundary, after all legacy V239/V240/V241
builder wrappers have run.
"""
from __future__ import annotations

import contextlib
from typing import Any

from neyrobot_prod import selfie_v241_authoritative_runtime as v241
from neyrobot_prod import selfie_v242_expression_lock as v242
from neyrobot_prod import selfie_v243_face_detail_restore as v243

VERSION = "v244-final-runtime-lock-2026-08-19"
_INSTALLED = False
_BUILDER_HOOKED = False


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


def enforce_runtime() -> None:
    """Reassert V243 after every older runtime owner."""
    # Keep V243 as the authoritative late-bound enforcer.
    v243.VERSION = VERSION
    v242.VERSION = VERSION
    v241.VERSION = VERSION
    v243.enforce_runtime()

    # Rebind the guarded generation entrypoint so a later V241 call cannot
    # restore the older prompt/merge implementation without V243 immediately
    # reasserting itself.
    v241.enforce_runtime = enforce_runtime
    v242.enforce_runtime = enforce_runtime

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v244-final-lock-v243-source-detail-v242-expression-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression-locked composition -> compact isolated real FaceSwap -> "
            "V243 source-guided detail -> final V244 runtime lock"
        )
    _log("AI_SELFIE_V244_ENFORCE status=ok owner=v243 detail=v243 expression=v242 faceswap=real version=%s", VERSION)


def _install_final_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_v244_final_runtime_lock_hooked"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return

    previous_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        # Older wrappers may patch during their own build. Let all of them run,
        # then take ownership again at the outermost/final boundary.
        app = previous_build(self, *args, **kwargs)
        enforce_runtime()
        with contextlib.suppress(Exception):
            from neyrobot_prod import selfie_v233_true_face_transfer as transfer
            transfer.bind_application(app)
        enforce_runtime()
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True


def install() -> None:
    global _INSTALLED

    # First initialize the exact V243 route that produced the desired transfer.
    v243.install()
    # Then add one final builder owner after every historical wrapper already
    # registered by sitecustomize/V239/V241.
    _install_final_builder_hook()
    enforce_runtime()

    if not _INSTALLED:
        _INSTALLED = True
        print("[neyrobot-prod] V244 final selfie runtime lock installed over V243", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
