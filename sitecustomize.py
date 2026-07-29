# -*- coding: utf-8 -*-
"""Production bootstrap.

V236 replaces the entire Telegram logic of the Celebrity Selfie mode with one
clean state machine. Legacy selfie modules may remain installed for catalogue,
admin and provider compatibility, but their public mode callbacks are no longer
used by the active flow.
"""
from __future__ import annotations

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}", flush=True)

# Keep catalogue/admin/provider installers available for the rest of the bot.
try:
    from neyrobot_prod.celebrity_selfie import install_async as install_catalogue
    install_catalogue()
except Exception as exc:
    print(f"[neyrobot-prod] celebrity catalogue warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from neyrobot_prod.selfie_commands_v206 import install_async as install_selfie_commands
    install_selfie_commands()
except Exception as exc:
    print(f"[neyrobot-prod] selfie commands warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from telegram.ext import ApplicationBuilder
    from neyrobot_prod import selfie_v236_clean_rewrite as clean

    CANONICAL_SELFIE_VERSION = clean.VERSION
    _builder_flag = "_neyrobot_v236_clean_rewrite_builder_hooked"

    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_clean_selfie(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            clean.bind_application(app)
            return app

        ApplicationBuilder.build = _build_with_clean_selfie
        setattr(ApplicationBuilder, _builder_flag, True)

    runtime = clean._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v236-clean-state-machine-google-scene-piapi-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct + PiAPI real FaceSwap"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY + PIAPI_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_USER_FULL_BODY_REFERENCES = 1
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        runtime.AI_SELFIE_REAL_FACESWAP = True

    print("[neyrobot-prod] V236 clean Celebrity Selfie rewrite installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] V236 clean selfie warning: {type(exc).__name__}: {exc}", flush=True)
