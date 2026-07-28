# -*- coding: utf-8 -*-
"""Load the production runtime before main.py.

Celebrity Selfie has one owner only. Older V208-V228 owner workers are deliberately
not started because they continuously rewrote the active generator and caused the
visible V229 package version to execute the legacy six-reference Comet route.
"""

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
    # V219 owns the complete three-photo UI/media flow. Its owner loop is retained,
    # but its patch function is wrapped so every iteration finishes by installing
    # the canonical two-stage direct-Google generator. No competing owner loops are
    # started anywhere else in this file.
    from neyrobot_prod import selfie_v219_triref_scene_owner as selfie_v219
    from neyrobot_prod import selfie_v229_canonical_two_stage as selfie_v229

    CANONICAL_SELFIE_VERSION = "v230-selfie-single-owner-two-stage-google-2026-07-28"
    _v219_original_patch_runtime = selfie_v219.patch_runtime

    def _canonical_selfie_patch_runtime():
        result = _v219_original_patch_runtime()
        selfie_v229.VERSION = CANONICAL_SELFIE_VERSION
        selfie_v229.patch_runtime()

        # Source-level aliases used by the already-bound V219 callback are resolved
        # at call time. Set them after every V219 patch, so the legacy generator and
        # its six-reference Comet caption cannot execute.
        selfie_v219.VERSION = CANONICAL_SELFIE_VERSION
        selfie_v219.generate = selfie_v229.generate

        runtime = selfie_v229._runtime()
        if runtime is not None:
            runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
            runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
            runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
            runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
            runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
            runtime.CELEBRITY_SELFIE_ROUTE = "v230-single-owner-direct-google-two-stage-9-or-10-refs"
            runtime.AI_SELFIE_PROVIDER = "Google Gemini direct only"
            runtime.AI_SELFIE_GENERATION_STAGES = 2
            runtime.AI_SELFIE_USER_REFERENCES = 3
            runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
            runtime.AI_SELFIE_HERO_REFERENCES = 3
        return result

    selfie_v219.patch_runtime = _canonical_selfie_patch_runtime
    selfie_v219.install_async()
    selfie_v229.install_async()
    _canonical_selfie_patch_runtime()
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V230 warning: {type(exc).__name__}: {exc}")
