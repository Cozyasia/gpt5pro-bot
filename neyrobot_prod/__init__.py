# -*- coding: utf-8 -*-
"""Neyro-Bot production package."""

# Successor compatibility markers retained for source-level regression tests:
# v253-yunet-source-pixel-lossless-2026-08-21
# v254-landmark-fit-seamless-source-2026-08-22
# v255-source-face-gate-lossless-2026-08-22
# v256-large-scale-source-pixels-2026-08-22
# v257-native-sampling-guard-2026-08-22
# v258-inner-face-integration-2026-08-24
# v259-eye-landmark-protection-2026-08-26
# v260-eye-roi-memory-safe-2026-08-26
# v261-edge-harmonization-2026-08-26
# v262-landmark-field-compositor-2026-08-27
# v263-dense-identity-lock-2026-08-27
VERSION = "v264-dense68-roi-production-2026-08-31"

# Production ownership is explicit. V263 remains as the dense-identity algorithm and
# model utility layer, but its old full-frame compositor is not production-accepted
# because production-size validation could restart a 512 MB Render process. V264 is
# the same 68-point identity contract with heavy image work restricted to PERSON-A ROI.
PRODUCTION_SELFIE_RUNTIME = "v264"
V263_PRODUCTION_ACCEPTED = False
V264_PRODUCTION_ACCEPTED = True

# V264 activation is attached to V247's existing internal overlay boundary instead
# of adding another Telegram callback/builder owner. V247 first installs V248..V262;
# then V263 model/runtime safety is armed and V264 becomes the sole final transfer
# owner. The bounded identity-core overlay refines only V264's already-existing
# strict candidate; if that optional refinement cannot install, base V264 remains.
# If V264 startup activation itself fails, the already-installed V262 owner remains.
try:
    from neyrobot_prod import selfie_v247_provider_supersample as _selfie_v247_module

    _v247_base_overlay = _selfie_v247_module._install_v248_overlay

    def _v264_after_v262_overlay() -> None:
        _v247_base_overlay()
        try:
            from neyrobot_prod import selfie_v262_landmark_field_compositor as _v262
            if not bool(getattr(_v262, "_INSTALLED", False)):
                _selfie_v247_module._log(
                    "AI_SELFIE_V264_INSTALL status=skipped reason=v262_not_installed rollback=v262"
                )
                return
            from neyrobot_prod.selfie_v263_runtime_safety import install as _install_v263_runtime_safety
            _install_v263_runtime_safety()
            from neyrobot_prod.selfie_v264_dense68_roi_production import install as _install_v264_identity
            _install_v264_identity()
            identity_core = "base_v264"
            try:
                from neyrobot_prod.selfie_v264_identity_core_refinement import install as _install_v264_identity_core
                _install_v264_identity_core()
                identity_core = "bounded_source_identity_core"
            except Exception as _identity_core_exc:
                _selfie_v247_module._log(
                    "AI_SELFIE_V264_IDENTITY_CORE_INSTALL status=failed fallback=base_v264 error=%s:%s",
                    type(_identity_core_exc).__name__, _identity_core_exc,
                )
            _selfie_v247_module._log(
                "AI_SELFIE_V264_INSTALL status=ok base=v262 landmarks=68 roi_only=true "
                "identity_core=%s rollback=v262_infra_only",
                identity_core,
            )
        except Exception as _v264_activation_exc:
            _selfie_v247_module._log(
                "AI_SELFIE_V264_INSTALL status=failed rollback=v262 error=%s:%s",
                type(_v264_activation_exc).__name__, _v264_activation_exc,
            )

    _selfie_v247_module._install_v248_overlay = _v264_after_v262_overlay
except Exception as _v264_hook_exc:
    print(
        f"[neyrobot-prod] V264 activation hook warning: {type(_v264_hook_exc).__name__}: {_v264_hook_exc}",
        flush=True,
    )

# Retouch is a UX/delivery overlay, not a Telegram route owner. It arms one
# ApplicationBuilder wrapper and patches the already-existing main.py helpers only
# after main.py has defined them. No callback/message/payment handlers are added.
try:
    from neyrobot_prod import retouch_v261_batch as _retouch_v261_module

    # PTB creates a fresh CallbackContext for each update in a Telegram media group,
    # while user_data is shared. Bind batch continuity to the shared user_data uid,
    # not object identity, and refresh the context used by the sequential worker.
    def _retouch_v261_shared_context(context):
        try:
            uid = int(context.user_data.get("_retouch_v261_uid") or 0)
        except Exception:
            uid = 0
        state = _retouch_v261_module._BATCH_STATES.get(uid)
        if state is not None:
            state["context"] = context
        return state

    _retouch_v261_module._state_for_context = _retouch_v261_shared_context
    _retouch_v261_module.install()
except Exception as _retouch_v261_exc:
    print(
        f"[neyrobot-prod] retouch V261 overlay warning: {type(_retouch_v261_exc).__name__}: {_retouch_v261_exc}",
        flush=True,
    )

__all__ = [
    "VERSION", "PRODUCTION_SELFIE_RUNTIME", "V263_PRODUCTION_ACCEPTED", "V264_PRODUCTION_ACCEPTED"
]
