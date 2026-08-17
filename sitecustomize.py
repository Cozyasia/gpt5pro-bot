# -*- coding: utf-8 -*-
"""Load production runtime before main.py.

V234 keeps the restored V232 scene workflow but makes the real FaceSwap stage the
absolute owner of generation button presses. Legacy V219/Comet handlers may remain
loaded for UI compatibility, but cannot win a generation callback.
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

    CANONICAL_SELFIE_VERSION = "v234-v232-scene-authoritative-faceswap-expression-2026-08-17"

    # Prepare the proven three-photo UI once, then stop its legacy owner loop.
    selfie_ui.patch_runtime()

    def _legacy_noop(*args, **kwargs):
        return True

    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    # V234 replaces the module-level generate symbols used by V229/V219 and also
    # owns an independent ultra-early callback handler at group -1000000.
    selfie_transfer.install_async()
    selfie_google.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie generation is disabled by V234")

    def _force_v234() -> None:
        selfie_google.generate = selfie_transfer.generate
        selfie_ui.generate = selfie_transfer.generate
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["generate"] = selfie_transfer.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route
        selfie_transfer.install()

    _force_v234()
    selfie_google.patch_runtime()
    _force_v234()

    _builder_flag = "_neyrobot_v234_authoritative_faceswap_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_v234(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_v234()
            selfie_google.bind_application(app)
            selfie_transfer.bind_application(app)
            _force_v234()
            return app

        ApplicationBuilder.build = _build_with_v234
        setattr(ApplicationBuilder, _builder_flag, True)

    # V229 still maintains the stable UI aliases; all aliases point back to V234.
    selfie_google.install_async()
    _force_v234()

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v234-gemini-scene-then-authoritative-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini composition + Segmind/PiAPI real FaceSwap"
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    print("[neyrobot-prod] V234 authoritative Gemini-scene + real-FaceSwap owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V234 warning: {type(exc).__name__}: {exc}", flush=True)
