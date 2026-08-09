# -*- coding: utf-8 -*-
"""Runtime bootstrap for the isolated Face Swap diagnostic."""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v261_identity_authority_diag as quality_diag

# Critical ordering: patch diag.media before any Telegram application binds its
# MessageHandler. Production AI-selfie is intentionally not modified here.
quality_diag.install()

VERSION = quality_diag.VERSION
_BUILDER_FLAG = "_faceswap_diag_v252_builder_hooked"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _is_app(value: Any) -> bool:
    return value is not None and callable(getattr(value, "add_handler", None)) and isinstance(getattr(value, "handlers", None), dict)


def bind_runtime_apps() -> int:
    mod = _runtime()
    if mod is None:
        return 0
    count = 0
    seen: set[int] = set()
    for value in vars(mod).values():
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        with contextlib.suppress(Exception):
            if _is_app(value):
                diag.bind_application(value)
                count += 1
    return count


def install_builder_hook() -> bool:
    from telegram.ext import ApplicationBuilder

    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return True
    original = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        quality_diag.install()
        diag.patch_main_keyboard()
        diag.patch_runtime_entertainment_menu()
        app = original(self, *args, **kwargs)
        diag.bind_application(app)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)
    return True


def install() -> bool:
    global _STARTED
    quality_diag.install()
    with contextlib.suppress(Exception):
        diag.patch_main_keyboard()
    with contextlib.suppress(Exception):
        diag.patch_runtime_entertainment_menu()
    install_builder_hook()
    bind_runtime_apps()
    if _STARTED:
        return True
    _STARTED = True

    def worker() -> None:
        for _ in range(7200):
            with contextlib.suppress(Exception):
                quality_diag.install()
            with contextlib.suppress(Exception):
                diag.patch_main_keyboard()
            with contextlib.suppress(Exception):
                diag.patch_runtime_entertainment_menu()
            with contextlib.suppress(Exception):
                bind_runtime_apps()
            time.sleep(0.5)

    threading.Thread(target=worker, daemon=True, name="neyrobot-faceswap-diag-v261").start()
    print(f"[neyrobot-prod] V261 Face Swap Identity Authority diagnostic installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install", "install_builder_hook", "bind_runtime_apps"]
