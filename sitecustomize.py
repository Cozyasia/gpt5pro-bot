# -*- coding: utf-8 -*-
"""Load the production runtime before main.py.

V233 preserves the proven V232/V219 selfie UI and the stable direct-Gemini scene
composition. The second synthetic Gemini identity pass is replaced by a real
FaceSwap transfer using the existing production FaceSwap providers, with strict
PERSON-A targeting and local face-only compositing.
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
    from neyrobot_prod import selfie_v233_true_face_transfer as selfie_transfer

    CANONICAL_SELFIE_VERSION = "v233-v232-gemini-true-face-transfer-2026-08-17"

    # Let V219 prepare its stable three-photo UI aliases exactly once.
    selfie_ui.patch_runtime()

    # Permanently stop every legacy rebinding path. The old worker resolves these
    # module globals on each iteration, so replacing them also neutralizes a worker
    # that may already have been started by an earlier bootstrap import.
    def _legacy_noop(*args, **kwargs):
        return True

    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    # Replace only the generation function. V229/V232 remains the canonical UI and
    # owner machinery, but now binds the V233 true FaceSwap transfer implementation.
    selfie_transfer.install()
    selfie_google.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError(
            "Legacy Comet selfie route is disabled; use V233 Gemini + true FaceSwap"
        )

    def _force_canonical_aliases() -> None:
        # V229's owner resolves its module-level `generate` dynamically. Since V233
        # replaced that symbol, every canonical alias now points to true face transfer.
        selfie_ui.generate = selfie_google.generate
        selfie_ui.public_callback.__globals__["generate"] = selfie_google.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route

    _force_canonical_aliases()
    selfie_google.patch_runtime()

    _builder_flag = "_neyrobot_v233_true_face_transfer_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_canonical_selfie(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_canonical_aliases()
            selfie_google.bind_application(app)
            selfie_google.patch_runtime()
            _force_canonical_aliases()
            return app

        ApplicationBuilder.build = _build_with_canonical_selfie
        setattr(ApplicationBuilder, _builder_flag, True)

    # Canonical owner remains last and continuously restores the V233 generate alias.
    selfie_google.install_async()
    _force_canonical_aliases()

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v233-v232-gemini-stage1-true-faceswap-stage2"
        runtime.AI_SELFIE_PROVIDER = "Gemini scene + Segmind/PiAPI true FaceSwap"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY + SEGMIND_API_KEY/PIAPI_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 2
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3

    print("[neyrobot-prod] V233 V232-Gemini + true FaceSwap selfie owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V233 warning: {type(exc).__name__}: {exc}")
