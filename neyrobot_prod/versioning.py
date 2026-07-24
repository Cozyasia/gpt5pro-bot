# -*- coding: utf-8 -*-
"""Canonical production release/version contract for Neyro-Bot v162.

Render starts ``main.py`` directly and ``secret_loader.py`` imports this module
before the Telegram Application is built.  The explicit startup owner therefore
installs v162, which retains v161 rendering and fixes the complete selfie wizard.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v162-unified-celebrity-selfie-flow-2026-07-24"
_INSTALLED = False
_BUILDER_HOOKED = False
_RUNTIME_STAMPER_STARTED = False
_RELEASE_OVERLAY_INSTALLED = False


def _install_current_release() -> bool:
    global _RELEASE_OVERLAY_INSTALLED
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap
        from neyrobot_prod.hotfix_v162 import install_early
        from neyrobot_prod.v162_flow_guard import install as install_flow_guard
        from neyrobot_prod.v161_reference_v2 import install as install_reference_v2

        install_early()
        install_flow_guard()
        install_reference_v2()
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        _RELEASE_OVERLAY_INSTALLED = True
        return True
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
    from neyrobot_prod.hotfix_v162 import _cmd_version as current
    await current(update, context)


def _install_builder_hook() -> None:
    """Let v162 own /version; it removes all historical duplicate handlers."""
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    try:
        from telegram.ext import ApplicationBuilder
        from neyrobot_prod.hotfix_v162 import install_builder_hook
        from neyrobot_prod.v162_flow_guard import install as install_flow_guard
    except Exception:
        return
    install_flow_guard()
    install_builder_hook()
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
        name="neyrobot-version-contract-v162",
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
