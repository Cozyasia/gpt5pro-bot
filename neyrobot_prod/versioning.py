# -*- coding: utf-8 -*-
"""Canonical production release/version contract."""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v158-fixed-roman-reference-pack-2026-07-23"
_INSTALLED = False
_BUILDER_HOOKED = False
_RUNTIME_STAMPER_STARTED = False
_RELEASE_OVERLAY_INSTALLED = False


def _install_current_release() -> bool:
    global _RELEASE_OVERLAY_INSTALLED
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap
        from celebrity_selfie_v158 import install as install_v158
        from celebrity_selfie_v158 import install_builder_hook as install_v158_builder

        install_v158()
        install_v158_builder()
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
    from telegram.ext import ApplicationHandlerStop

    release_overlay = _install_current_release()
    mod = _runtime_module()
    if mod is not None:
        _stamp_runtime(mod)

    general_router = getattr(mod, "GENERAL_TEXT_ROUTER_VERSION", "—") if mod is not None else "—"
    medical_card = getattr(mod, "MEDICAL_CARD_VERSION", "—") if mod is not None else "—"
    medical_ui = getattr(mod, "MEDICAL_ANSWER_UI_VERSION", "—") if mod is not None else "—"
    medical_text = bool(
        mod is not None
        and getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v120_medical", False)
    )
    medical_image = bool(
        mod is not None
        and getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v120_medical", False)
    )

    lines = [
        f"✅ Код запущен: {VERSION}",
        "entrypoint=main.py",
        "start_command=python -u main.py",
        f"release_overlay={'v158' if release_overlay else 'load-error'}",
        "celebrity_selfie_menu=v124-exclusive-catalog-and-scene-wizard",
        "celebrity_selfie_render=v156-comet-dual-identity-best-of-n",
        "fixed_roman_references=v158-repository-owner-pack-3",
        "false_submenu_error=v158-removed",
        "selected_celebrity_identity=hard-gated-and-dominant",
        "generic_nano_banana_route=blocked_inside_celebrity_wizard",
        "legacy_selfie_overlays=inactive",
        f"general_router={general_router}",
        f"medical_text_route={'v120' if medical_text else 'legacy'}",
        f"medical_image_route={'v120' if medical_image else 'legacy'}",
        f"medical_answer_ui={medical_ui}",
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
        name="neyrobot-version-contract-v158",
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
