# -*- coding: utf-8 -*-
"""Load the production runtime before main.py.

V234 preserves V233 on backup/v233-2026-07-29-before-v234 and activates one
hybrid owner: direct Google Gemini for scene/body composition followed by a
specialized PiAPI FaceSwap crop/composite pass for the user's real face.
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
    from neyrobot_prod import selfie_v234_full_body_guard as selfie_media_guard

    CANONICAL_SELFIE_VERSION = "v234-selfie-hybrid-real-faceswap-2026-07-29"

    selfie_ui.patch_runtime()

    def _legacy_noop(*args, **kwargs):
        return True

    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    selfie_hybrid.VERSION = CANONICAL_SELFIE_VERSION
    selfie_v233.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie route is disabled by V234")

    def _publish_runtime_metadata() -> None:
        runtime = selfie_hybrid._runtime()
        if runtime is None:
            return
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v234-google-scene-plus-piapi-real-faceswap-crop-composite"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini + PiAPI FaceSwap"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY + PIAPI_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_USER_FULL_BODY_REFERENCES = 1
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        runtime.AI_SELFIE_REAL_FACESWAP = True

    def _force_canonical_aliases() -> None:
        selfie_v233.generate = selfie_hybrid.generate
        selfie_ui.generate = selfie_hybrid.generate
        selfie_ui.public_callback.__globals__["generate"] = selfie_hybrid.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route
        selfie_hybrid.patch_runtime()
        _publish_runtime_metadata()

    _force_canonical_aliases()

    _builder_flag = "_neyrobot_v234_hybrid_faceswap_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_canonical_selfie(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_canonical_aliases()
            selfie_hybrid.bind_application(app)
            selfie_media_guard.bind_application(app)
            _force_canonical_aliases()
            _publish_runtime_metadata()
            return app

        ApplicationBuilder.build = _build_with_canonical_selfie
        setattr(ApplicationBuilder, _builder_flag, True)

    selfie_hybrid.install_async()
    _force_canonical_aliases()
    _publish_runtime_metadata()

    print("[neyrobot-prod] V234 hybrid Gemini + real PiAPI FaceSwap owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V234 warning: {type(exc).__name__}: {exc}")
