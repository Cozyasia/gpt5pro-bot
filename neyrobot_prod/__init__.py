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
VERSION = "v263-dense-identity-lock-2026-08-27"

# V263 activation is attached to V247's existing internal overlay boundary instead
# of adding another Telegram callback/builder owner. V247's original overlay first
# installs V248..V262; only then is V263 armed. If V263 fails, V262 remains active.
try:
    from neyrobot_prod import selfie_v247_provider_supersample as _selfie_v247_module

    _v247_base_overlay = _selfie_v247_module._install_v248_overlay

    def _v263_after_v262_overlay() -> None:
        _v247_base_overlay()
        try:
            from neyrobot_prod import selfie_v262_landmark_field_compositor as _v262
            if not bool(getattr(_v262, "_INSTALLED", False)):
                return
            from neyrobot_prod.selfie_v263_runtime_safety import install as _install_v263_runtime_safety
            _install_v263_runtime_safety()
            from neyrobot_prod.selfie_v263_dense_identity_lock import install as _install_v263_identity
            _install_v263_identity()
            _selfie_v247_module._log("AI_SELFIE_V263_INSTALL status=ok base=v262 rollback=v262")
        except Exception as _v263_activation_exc:
            _selfie_v247_module._log(
                "AI_SELFIE_V263_INSTALL status=failed rollback=v262 error=%s:%s",
                type(_v263_activation_exc).__name__, _v263_activation_exc,
            )

    _selfie_v247_module._install_v248_overlay = _v263_after_v262_overlay
except Exception as _v263_hook_exc:
    print(
        f"[neyrobot-prod] V263 activation hook warning: {type(_v263_hook_exc).__name__}: {_v263_hook_exc}",
        flush=True,
    )

# Retouch is a UX/delivery overlay, not a Telegram route owner.  It arms one
# ApplicationBuilder wrapper and patches the already-existing main.py helpers only
# after main.py has defined them.  No callback/message/payment handlers are added.
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

__all__ = ["VERSION"]
