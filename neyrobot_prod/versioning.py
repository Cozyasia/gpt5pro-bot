# -*- coding: utf-8 -*-
"""Canonical release version contract for the production bot.

Legacy feature overlays keep their own component versions and may update
``PATCH_VERSION`` while they are installed.  The public ``/version`` command,
however, must always report the actual production release that Render runs.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

from . import VERSION

_INSTALLED = False
_BUILDER_HOOKED = False
_RUNTIME_STAMPER_STARTED = False


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _stamp_runtime(mod: Any) -> None:
    """Expose one canonical release identifier despite legacy overlay races."""
    mod.APP_VERSION = VERSION
    mod.RELEASE_VERSION = VERSION
    mod.PRODUCTION_HARDENING_VERSION = VERSION
    mod.PATCH_VERSION = VERSION


async def _cmd_version(update: Any, context: Any) -> None:
    """Return the canonical release and stop legacy /version handlers."""
    from telegram.ext import ApplicationHandlerStop

    mod = _runtime_module()
    if mod is not None:
        _stamp_runtime(mod)

    general_router = getattr(mod, "GENERAL_TEXT_ROUTER_VERSION", "—") if mod is not None else "—"
    medical_card = getattr(mod, "MEDICAL_CARD_VERSION", "—") if mod is not None else "—"
    medical_text = bool(
        mod is not None
        and getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v119_medical", False)
    )
    medical_image = bool(
        mod is not None
        and getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v119_medical", False)
    )

    lines = [
        f"✅ Код запущен: {VERSION}",
        "entrypoint=main.py",
        "start_command=python -u main.py",
        f"general_router={general_router}",
        f"medical_text_route={'v119' if medical_text else 'legacy'}",
        f"medical_image_route={'v119' if medical_image else 'legacy'}",
        f"medical_card={medical_card}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


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
        if not getattr(app, "_neyrobot_version_contract_handler", False):
            # A very early group plus ApplicationHandlerStop guarantees that an
            # old overlay cannot send a second, stale version response.
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
        # Keep the canonical release visible even if a legacy overlay installs
        # later and writes its component version into PATCH_VERSION.
        while True:
            mod = _runtime_module()
            if mod is not None:
                with contextlib.suppress(Exception):
                    _stamp_runtime(mod)
            time.sleep(2.0)

    threading.Thread(
        target=worker,
        name="neyrobot-version-contract",
        daemon=True,
    ).start()


def install_early() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_builder_hook()
    _start_runtime_stamper()
    _INSTALLED = True


__all__ = ["install_early", "VERSION"]
