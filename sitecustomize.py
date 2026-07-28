# -*- coding: utf-8 -*-
"""Load the production runtime before main.py.

Celebrity Selfie has one canonical owner. The legacy V219 module is retained only
for its proven three-photo UI/media helpers. Its background owner loop is never
started. Every generation callback is routed to the two-stage direct Google
Gemini pipeline using only GEMINI_IMAGE_API_KEY.
"""

import contextlib

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.celebrity_selfie import install_async as install_celebrity_selfie
    install_celebrity_selfie()
except Exception as exc:
    print(f"[neyrobot-prod] celebrity selfie warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_commands_v206 import install_async as install_selfie_commands
    install_selfie_commands()
except Exception as exc:
    print(f"[neyrobot-prod] selfie commands warning: {type(exc).__name__}: {exc}")

try:
    from telegram.ext import ApplicationBuilder
    from neyrobot_prod import selfie_v219_triref_scene_owner as selfie_ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as selfie_google

    CANONICAL_SELFIE_VERSION = "v231-selfie-source-canonical-two-stage-google-2026-07-28"

    # Prepare the complete V219 UI once, but deliberately do not call
    # selfie_ui.install_async(): its legacy worker restores the six-reference
    # Comet generator every 100 ms.
    selfie_ui.patch_runtime()

    # Replace the globals resolved by the already-defined V219 callback itself.
    # This is stronger than changing a visible package version or a detached alias.
    selfie_google.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.generate = selfie_google.generate
    selfie_ui.public_callback.__globals__["generate"] = selfie_google.generate

    # Comet is a hard failure for this mode. If any stale callback somehow reaches
    # the old helper, it must fail rather than silently spend through CometAPI.
    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError(
            "Legacy Comet selfie route is disabled; canonical direct Google handler must own generation"
        )

    selfie_ui._comet_generate = _disabled_comet_route
    with contextlib.suppress(Exception):
        selfie_ui.generate.__globals__["_comet_generate"] = _disabled_comet_route

    # Install the canonical generation callback into every existing application.
    selfie_google.patch_runtime()

    # Guarantee installation for applications built after sitecustomize finishes.
    _builder_flag = "_neyrobot_v231_canonical_selfie_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_canonical_selfie(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            selfie_ui.patch_runtime()
            selfie_ui.generate = selfie_google.generate
            selfie_ui.public_callback.__globals__["generate"] = selfie_google.generate
            selfie_ui._comet_generate = _disabled_comet_route
            selfie_google.bind_application(app)
            selfie_google.patch_runtime()
            return app

        ApplicationBuilder.build = _build_with_canonical_selfie
        setattr(ApplicationBuilder, _builder_flag, True)

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v231-source-canonical-direct-google-two-stage-9-or-10-refs"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 2
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3

    # Only the canonical Google owner is allowed to maintain runtime bindings.
    selfie_google.install_async()
    print("[neyrobot-prod] V231 canonical direct-Google selfie owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V231 warning: {type(exc).__name__}: {exc}")
