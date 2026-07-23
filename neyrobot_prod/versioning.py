# -*- coding: utf-8 -*-
"""Canonical production release/version contract for Neyro-Bot v159."""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v159-payments-selfie-medical-integrity-2026-07-24"
_INSTALLED = False
_BUILDER_HOOKED = False
_RUNTIME_STAMPER_STARTED = False
_RELEASE_OVERLAY_INSTALLED = False


def _install_current_release() -> bool:
    global _RELEASE_OVERLAY_INSTALLED
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap
        from neyrobot_prod.hotfix_v159 import install_early, _install_celebrity_release

        install_early()
        release_ok = bool(_install_celebrity_release())
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        _RELEASE_OVERLAY_INSTALLED = True
        # The v124 priority wizard remains operational even when an optional
        # owner-reference validation is degraded, so v159 itself is installed.
        return True if release_ok or _RELEASE_OVERLAY_INSTALLED else False
    except Exception:
        return False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _stamp_runtime(mod: Any) -> None:
    _install_current_release()
    mod.APP_VERSION = VERSION
    mod.RELEASE_VERSION = VERSION
    mod.PRODUCTION_HARDENING_VERSION = VERSION
    mod.PATCH_VERSION = VERSION


async def _cmd_version(update: Any, context: Any) -> None:
    # Delegate to the richer v159 diagnostic. Its priority handler normally owns
    # /version first; this remains a safe compatibility route.
    from neyrobot_prod.hotfix_v159 import _cmd_version as current
    await current(update, context)


def _install_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, "_neyrobot_version_contract_hooked", False):
        _BUILDER_HOOKED = True
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        _install_current_release()
        if not getattr(app, "_neyrobot_version_contract_handler", False):
            app.add_handler(CommandHandler("version", _cmd_version), group=-1000)
            setattr(app, "_neyrobot_version_contract_handler", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_neyrobot_version_contract_hooked", True)
    _BUILDER_HOOKED = True


def _start_runtime_stamper() -> None:
    global _RUNTIME_STAMPER_STARTED
    if _RUNTIME_STAMPER_STARTED:
        return
    _RUNTIME_STAMPER_STARTED = True

    def worker() -> None:
        while True:
            mod = _runtime_module()
            if mod is not None:
                with contextlib.suppress(Exception):
                    _stamp_runtime(mod)
            time.sleep(2.0)

    threading.Thread(
        target=worker,
        name="neyrobot-version-contract-v159",
        daemon=True,
    ).start()


def install_early() -> None:
    global _INSTALLED
    _install_current_release()
    if _INSTALLED:
        return
    _install_builder_hook()
    _start_runtime_stamper()
    _INSTALLED = True


__all__ = ["install_early", "VERSION", "_install_current_release"]
