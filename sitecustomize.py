# -*- coding: utf-8 -*-
"""Load the production runtime before main.py.

V235 keeps the stable V234 provider pipeline but takes ownership of the actual
registered Telegram callbacks. This prevents the legacy six-reference Comet
handler from surviving behind a newer version marker.
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
    from neyrobot_prod import selfie_v233_body_face_transplant as selfie_v233
    from neyrobot_prod import selfie_v234_hybrid_faceswap as selfie_hybrid
    from neyrobot_prod import selfie_v235_hard_owner as selfie_owner

    CANONICAL_SELFIE_VERSION = selfie_owner.VERSION

    # Let V219 build its proven keyboards/catalogue once, then prevent every
    # background installer from restoring the old provider route.
    selfie_ui.patch_runtime()

    def _legacy_noop(*args, **kwargs):
        return True

    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    selfie_owner.patch_runtime()
    selfie_owner.VERSION = CANONICAL_SELFIE_VERSION
    selfie_hybrid.VERSION = CANONICAL_SELFIE_VERSION
    selfie_v233.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie route is disabled by V235")

    def _force_owner() -> None:
        selfie_owner.patch_runtime()
        selfie_v233.generate = selfie_owner.generate
        selfie_ui.generate = selfie_owner.generate
        selfie_ui.public_callback.__globals__["generate"] = selfie_owner.generate
        selfie_ui.public_text.__globals__["generate"] = selfie_owner.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route

    _force_owner()

    _builder_flag = "_neyrobot_v235_hard_owner_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_owner(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_owner()
            selfie_owner.bind_application(app)
            _force_owner()
            return app

        ApplicationBuilder.build = _build_with_owner
        setattr(ApplicationBuilder, _builder_flag, True)

    runtime = selfie_owner._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v235-hard-handler-owner-google-scene-piapi-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct + PiAPI FaceSwap"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY + PIAPI_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_USER_FULL_BODY_REFERENCES = 1
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        runtime.AI_SELFIE_REAL_FACESWAP = True

    print("[neyrobot-prod] V235 hard selfie handler owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V235 warning: {type(exc).__name__}: {exc}")
