# -*- coding: utf-8 -*-
"""Load the production runtime before main.py.

V233 preserves the V232 code on backup/v232-2026-07-29-before-v233 and activates
one direct-Google body-first / localized-face-transplant Celebrity Selfie owner.
Only GEMINI_IMAGE_API_KEY is accepted; Comet selfie generation is disabled.
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
    from neyrobot_prod import selfie_v233_body_face_transplant as selfie_google

    CANONICAL_SELFIE_VERSION = "v233-selfie-body-face-transplant-google-2026-07-29"

    # Prepare the proven three-face UI once, then permanently stop every legacy
    # owner/rebinding path that could restore the six-reference Comet generator.
    selfie_ui.patch_runtime()

    def _legacy_noop(*args, **kwargs):
        return True

    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    selfie_google.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie route is disabled by V233")

    def _force_canonical_aliases() -> None:
        selfie_ui.generate = selfie_google.generate
        selfie_ui.public_callback.__globals__["generate"] = selfie_google.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route
        selfie_google.patch_runtime()

    _force_canonical_aliases()

    _builder_flag = "_neyrobot_v233_body_face_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_canonical_selfie(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_canonical_aliases()
            selfie_google.bind_application(app)
            _force_canonical_aliases()
            return app

        ApplicationBuilder.build = _build_with_canonical_selfie
        setattr(ApplicationBuilder, _builder_flag, True)

    selfie_google.install_async()
    _force_canonical_aliases()

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v233-body-first-localized-face-transplant-google-three-stage"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_CROPS = 3
        runtime.AI_SELFIE_USER_FULL_BODY_REFERENCES = 1
        runtime.AI_SELFIE_HERO_REFERENCES = 3

    print("[neyrobot-prod] V233 body-first face-transplant direct-Google owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V233 warning: {type(exc).__name__}: {exc}")
