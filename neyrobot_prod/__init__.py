# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

V257 removes legacy AI Selfie production monkey-patch bootstraps from package
import. The stable secret_loader owner routes production generation to the
consolidated V257 runtime. The production fidelity overlay enforces camera framing,
bounded latency, universal FullHD face quality, source-expression preservation,
restart-safe AI Selfie upload state, bounded target rescue, close composition
normalization, a mandatory fresh hero-selection gate for new photo sets,
provider-resilient identity transfer with geometry-safe restoration after padded
remote face-swap retries, V287 first-pass native reference quality with
principal-face-pair reframing, V288 detector-safe PiAPI identity canvases, V289b
deterministic source-native identity after the runtime has verified PERSON A,
V292 source-authoritative facial geometry with face-safe final integration, V293
strict selfie anatomy/close-framing validation, V294 nonblocking Stage-1
reference preparation with a hard composition watchdog, and V295b provider-adapted
identity transfer that deliberately disables the V295 direct source-pixel face
re-lock. Photo #3 remains the identity source, while the provider adapts identity
to target pose and lighting without a pasted affine facial patch.
"""

VERSION = "v206-selfie-command-routing-2026-07-25"
AI_SELFIE_VERSION = "v295b-provider-adapted-identity-no-source-paste-2026-08-17"

try:
    from .render_lifecycle_diag import install as _install_render_lifecycle_diag
    _install_render_lifecycle_diag()
except Exception as _lifecycle_error:
    print(f"[neyrobot-prod] Render lifecycle diagnostic bootstrap failed: {_lifecycle_error!r}", flush=True)

try:
    from .selfie_v246_faceswap_diag_bootstrap import install as _install_faceswap_diag
    _install_faceswap_diag()
except Exception as _diag_error:
    print(f"[neyrobot-prod] Face Swap diagnostic bootstrap failed: {_diag_error!r}", flush=True)

try:
    from .selfie_v277_production_fidelity_patch import install as _install_selfie_fidelity
    _install_selfie_fidelity()
except Exception as _fidelity_error:
    print(f"[neyrobot-prod] production selfie fidelity bootstrap failed: {_fidelity_error!r}", flush=True)

try:
    from .selfie_v283_terminal_target_rescue import install as _install_selfie_target_rescue
    _install_selfie_target_rescue()
except Exception as _target_rescue_error:
    print(f"[neyrobot-prod] selfie terminal target rescue bootstrap failed: {_target_rescue_error!r}", flush=True)

try:
    from .selfie_v284_close_framing_and_hero_gate import install as _install_selfie_v284
    _install_selfie_v284()
except Exception as _v284_error:
    print(f"[neyrobot-prod] V284 close framing/hero gate bootstrap failed: {_v284_error!r}", flush=True)

try:
    from .selfie_v285_identity_fallback import install as _install_selfie_v286
    _install_selfie_v286()
except Exception as _v286_error:
    print(f"[neyrobot-prod] V286 identity geometry resilience bootstrap failed: {_v286_error!r}", flush=True)

try:
    from .selfie_v287_first_pass_quality import install as _install_selfie_v287
    _install_selfie_v287()
except Exception as _v287_error:
    print(f"[neyrobot-prod] V287 first-pass quality bootstrap failed: {_v287_error!r}", flush=True)

try:
    from .selfie_v288_detector_safe_identity import install as _install_selfie_v288
    _install_selfie_v288()
except Exception as _v288_error:
    print(f"[neyrobot-prod] V288 detector-safe identity bootstrap failed: {_v288_error!r}", flush=True)

try:
    from .selfie_v289_native_identity_primary import install as _install_selfie_v289
    _install_selfie_v289()
except Exception as _v289_error:
    print(f"[neyrobot-prod] V289 native identity primary bootstrap failed: {_v289_error!r}", flush=True)

try:
    from .selfie_v290_gaze_quality_singleflight import install as _install_selfie_v292
    _install_selfie_v292()
except Exception as _v292_error:
    print(f"[neyrobot-prod] V292 identity/integration bootstrap failed: {_v292_error!r}", flush=True)

try:
    from .selfie_v293_selfie_composition_gate import install as _install_selfie_v293
    _install_selfie_v293()
except Exception as _v293_error:
    print(f"[neyrobot-prod] V293 selfie anatomy/framing gate bootstrap failed: {_v293_error!r}", flush=True)

try:
    from .selfie_v294_stage1_watchdog import install as _install_selfie_v294
    _install_selfie_v294()
except Exception as _v294_error:
    print(f"[neyrobot-prod] V294 Stage-1 watchdog bootstrap failed: {_v294_error!r}", flush=True)

try:
    from .selfie_v295_identity_fidelity_lock import install as _install_selfie_v295
    _install_selfie_v295()
except Exception as _v295_error:
    print(f"[neyrobot-prod] V295b provider-adapted identity bootstrap failed: {_v295_error!r}", flush=True)

try:
    from .selfie_v281_restart_resilience import install as _install_selfie_restart_resilience
    _install_selfie_restart_resilience()
except Exception as _restart_error:
    print(f"[neyrobot-prod] selfie restart resilience bootstrap failed: {_restart_error!r}", flush=True)

__all__ = ["VERSION", "AI_SELFIE_VERSION"]