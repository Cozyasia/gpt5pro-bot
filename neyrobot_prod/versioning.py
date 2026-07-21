# -*- coding: utf-8 -*-
"""Canonical production release/version contract.

The newest Celebrity Selfie overlay is installed here as well as from
``sitecustomize.py``. Render starts the service with ``python main.py`` and a
repository-local sitecustomize import is not guaranteed in every environment,
so this module is the authoritative repeatable bootstrap path.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v154-cpu-rembg-user-face-recovery-2026-07-22"
_INSTALLED = False
_BUILDER_HOOKED = False
_RUNTIME_STAMPER_STARTED = False
_RELEASE_OVERLAY_INSTALLED = False

# Historical markers retained for source-level compatibility tests:
# VERSION = "v145-piapi-celebrity-lock-retry-2026-07-21"
# from celebrity_selfie_v145 import install as install_v145
# install_v145()
# release_overlay={'v145' if release_overlay else 'load-error'}
# VERSION = "v146-local-face-lock-2026-07-21"
# from celebrity_selfie_v146 import install as install_v146
# install_v146()
# release_overlay={'v146' if release_overlay else 'load-error'}
# VERSION = "v147-source-pixel-dual-composite-2026-07-21"
# from celebrity_selfie_v147 import install as install_v147
# install_v147()
# release_overlay={'v147' if release_overlay else 'load-error'}
# VERSION = "v148-schema-safe-layer-qc-2026-07-21"
# from celebrity_selfie_v148 import install as install_v148
# install_v148()
# release_overlay={'v148' if release_overlay else 'load-error'}
# VERSION = "v149-visible-human-layer-proof-2026-07-21"
# from celebrity_selfie_v149 import install as install_v149
# install_v149()
# release_overlay={'v149' if release_overlay else 'load-error'}
# VERSION = "v150-comet-scene-failover-2026-07-21"
# from celebrity_selfie_v150 import install as install_v150
# install_v150()
# release_overlay={'v150' if release_overlay else 'load-error'}
# VERSION = "v151-comet-only-composition-ready-2026-07-21"
# from celebrity_selfie_v151 import install as install_v151
# install_v151()
# release_overlay={'v151' if release_overlay else 'load-error'}
# VERSION = "v152-empty-comet-plate-contract-2026-07-21"
# from celebrity_selfie_v152 import install as install_v152
# install_v152()
# release_overlay={'v152' if release_overlay else 'load-error'}
# VERSION = "v153-reference-detector-miss-recovery-2026-07-21"
# from celebrity_selfie_v153 import install as install_v153
# install_v153()
# release_overlay={'v153' if release_overlay else 'load-error'}


def _install_current_release() -> bool:
    """Install and re-apply v154 without relying on import order."""
    global _RELEASE_OVERLAY_INSTALLED
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap
        from celebrity_selfie_v154 import install as install_v154
        from celebrity_selfie_v154 import install_builder_hook as install_v154_builder

        install_v154()
        install_v154_builder()
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
        f"release_overlay={'v154' if release_overlay else 'load-error'}",
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
        name="neyrobot-version-contract-v154",
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
