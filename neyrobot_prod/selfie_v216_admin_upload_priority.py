# -*- coding: utf-8 -*-
"""V216 canonical admin upload priority for Celebrity Selfie.

V215 public media handlers run at a very early PTB group. Legacy /selfie_admin
routing could still create ``ss205_admin_upload`` while V215 checked only the
newer ``cs212_admin_upload`` key. A hero JPEG was therefore interpreted as a
user photo whenever two user photos were already cached.

V216 makes the V212 full catalogue the canonical /selfie_admin command and
routes every known admin-upload state before any public user-photo or uploaded-
scene logic. Existing V205/V202/V201 upload sessions remain compatible.
"""
from __future__ import annotations

import contextlib
import sys
from typing import Any

VERSION = "v216-selfie-admin-upload-priority-2026-07-26"


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _admin_state_name(context: Any) -> str:
    """Return the active upload protocol in strict newest-to-oldest order."""
    for key in (
        "cs212_admin_upload",
        "ss205_admin_upload",
        "cs202_admin_upload",
        "cs201_admin_upload",
    ):
        if context.user_data.get(key):
            return key
    return ""


async def canonical_admin_command(update: Any, context: Any) -> None:
    """Always open the V212 country catalogue, including V215's new heroes."""
    from neyrobot_prod import selfie_admin_v212_catalog as admin_v212

    await admin_v212.command(update, context)


async def media_router(update: Any, context: Any) -> None:
    """Give hero-reference uploads absolute priority over public photo routing."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_admin_v202 as admin_v202
    from neyrobot_prod import selfie_admin_v212_catalog as admin_v212
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215

    state_name = _admin_state_name(context)
    if state_name:
        # A stale public flow must never classify an owner reference as a user
        # identity photo or uploaded scene. The delegated handler performs access
        # checks, saves the JPEG and raises ApplicationHandlerStop itself.
        context.user_data.pop("cs215_await_scene_image", None)
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        context.user_data.pop("cs215_wait_scene_text", None)
        if state_name == "cs212_admin_upload":
            await admin_v212.media(update, context)
            raise ApplicationHandlerStop
        if state_name == "ss205_admin_upload":
            await storage_v205.media_entry(update, context)
            raise ApplicationHandlerStop
        if state_name == "cs202_admin_upload":
            await admin_v202.media(update, context)
            raise ApplicationHandlerStop
        if state_name == "cs201_admin_upload":
            await base.media_entry(update, context)
            raise ApplicationHandlerStop

    await v215.public_media(update, context)


def patch_runtime() -> bool:
    """Publish the canonical command and media router before Application build."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_admin_v212_catalog as admin_v212
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v210_generation_guard as v210
    from neyrobot_prod import selfie_v211_delivery as v211
    from neyrobot_prod import selfie_v213_user_identity_lock as v213
    from neyrobot_prod import selfie_v214_reuse_controls as v214
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215

    # V209's early command and media handlers read these attributes when the PTB
    # Application is built, so assigning them here makes V216 the actual owner.
    v208._admin_command = canonical_admin_command
    v208._public_media = media_router
    base.media_entry = media_router
    storage_v205.admin_command = canonical_admin_command

    for module in (
        v208,
        v209,
        v210,
        v211,
        v213,
        v214,
        v215,
        admin_v212,
        commands_v206,
        runtime_v207,
        storage_v205,
    ):
        module.VERSION = VERSION

    runtime = _runtime_module()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = (
            "v216-shot-scene-admin-upload-priority-7-or-8-reference"
        )
        runtime.SELFIE_ADMIN_UPLOAD_PRIORITY = True
        runtime.SELFIE_ADMIN_UPLOAD_STATE_KEYS = (
            "cs212_admin_upload",
            "ss205_admin_upload",
            "cs202_admin_upload",
            "cs201_admin_upload",
        )
    return True


def install_async() -> None:
    patch_runtime()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "canonical_admin_command",
    "media_router",
    "patch_runtime",
    "install_async",
    "install",
]
