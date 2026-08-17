# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

V257 removes legacy AI Selfie production monkey-patch bootstraps from package
import. The stable secret_loader owner routes production generation to the
consolidated V257 runtime. The production fidelity overlay enforces camera framing,
bounded latency, universal face quality, source-expression preservation,
restart-safe AI Selfie upload state, bounded target rescue, close composition
normalization, a mandatory fresh hero-selection gate for new photo sets,
provider-resilient identity transfer with geometry-safe restoration after padded
remote face-swap retries, V287 first-pass native reference quality with
principal-face-pair reframing, V288 detector-safe PiAPI identity canvases, V289b
deterministic source-native identity after the runtime has verified PERSON A,
V292 source-authoritative facial geometry with face-safe final integration, V297
close-selfie prompting, V299 low-memory sequential identity transfer, V300
bounded Stage-1, V301 fast source detection plus cross-provider Stage-1 recovery,
V302 rescue from an unavailable OpenAI Responses fallback to Gemini Pro, V303
direct OpenAI Images fallback without a text-model orchestrator, V304 compact
OpenAI-first Stage-1 for production selfie latency, V305 fast PERSON-A target
locking with no repeated legacy detector passes, V306 asynchronous Replicate
identity transport with real provider failover, and V307 bounded parallel identity
providers with face-aware PiAPI rescue. Photo #3 remains the sole user identity source.
"""

VERSION = "v206-selfie-command-routing-2026-07-25"
AI_SELFIE_VERSION = "v307-bounded-identity-race-face-aware-piapi-2026-08-17"

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
    print(f"[neyrobot-prod] V297 selfie prompt bootstrap failed: {_v293_error!r}", flush=True)

try:
    from .selfie_v294_stage1_watchdog import install as _install_selfie_v294
    _install_selfie_v294()
except Exception as _v294_error:
    print(f"[neyrobot-prod] V297 Stage-1 total-budget bootstrap failed: {_v294_error!r}", flush=True)

try:
    from .selfie_v295_identity_fidelity_lock import install as _install_selfie_v295
    _install_selfie_v295()
except Exception as _v295_error:
    print(f"[neyrobot-prod] V299 low-memory identity bootstrap failed: {_v295_error!r}", flush=True)

try:
    from .selfie_v298_single_pass_stage1 import install as _install_selfie_v300
    _install_selfie_v300()
except Exception as _v300_error:
    print(f"[neyrobot-prod] V300 bounded Stage-1 bootstrap failed: {_v300_error!r}", flush=True)

try:
    from .selfie_v301_fast_resilient_stage1 import install as _install_selfie_v301
    _install_selfie_v301()
except Exception as _v301_error:
    print(f"[neyrobot-prod] V301 fast/cross-provider Stage-1 bootstrap failed: {_v301_error!r}", flush=True)

try:
    from .selfie_v302_openai_fallback_rescue import install as _install_selfie_v302
    _install_selfie_v302()
except Exception as _v302_error:
    print(f"[neyrobot-prod] V302 OpenAI fallback rescue bootstrap failed: {_v302_error!r}", flush=True)

try:
    from .selfie_v303_direct_openai_images import install as _install_selfie_v303
    _install_selfie_v303()
except Exception as _v303_error:
    print(f"[neyrobot-prod] V303 direct OpenAI Images bootstrap failed: {_v303_error!r}", flush=True)

try:
    from .selfie_v304_compact_stage1 import install as _install_selfie_v304
    _install_selfie_v304()
except Exception as _v304_error:
    print(f"[neyrobot-prod] V304 compact Stage-1 bootstrap failed: {_v304_error!r}", flush=True)

try:
    from .selfie_v305_fast_target_lock import install as _install_selfie_v305
    _install_selfie_v305()
except Exception as _v305_error:
    print(f"[neyrobot-prod] V305 fast target bootstrap failed: {_v305_error!r}", flush=True)

try:
    from .selfie_v306_identity_transport import install as _install_selfie_v306
    _install_selfie_v306()
except Exception as _v306_error:
    print(f"[neyrobot-prod] V306 identity transport bootstrap failed: {_v306_error!r}", flush=True)

# V307 is last on purpose: it keeps V306's async Replicate transport but replaces
# the sequential provider policy with a bounded race and a face-aware PiAPI branch.
try:
    from .selfie_v307_identity_race import install as _install_selfie_v307
    _install_selfie_v307()
except Exception as _v307_error:
    print(f"[neyrobot-prod] V307 identity race bootstrap failed: {_v307_error!r}", flush=True)

try:
    from .selfie_v281_restart_resilience import install as _install_selfie_restart_resilience
    _install_selfie_restart_resilience()
except Exception as _restart_error:
    print(f"[neyrobot-prod] selfie restart resilience bootstrap failed: {_restart_error!r}", flush=True)

__all__ = ["VERSION", "AI_SELFIE_VERSION"]
