# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

V257 removes legacy AI Selfie production monkey-patch bootstraps from package
import. The stable secret_loader owner routes production generation to the
consolidated V257 runtime. The production fidelity overlay enforces camera framing,
bounded latency, universal FullHD face quality, source-expression preservation,
restart-safe AI Selfie upload state, bounded target rescue, close composition
normalization, a mandatory fresh hero-selection gate for new photo sets, and
provider-resilient identity transfer with geometry-safe restoration after padded
remote face-swap retries.
"""

VERSION = "v206-selfie-command-routing-2026-07-25"
AI_SELFIE_VERSION = "v286-identity-geometry-safe-2026-08-16"

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
    from .selfie_v281_restart_resilience import install as _install_selfie_restart_resilience
    _install_selfie_restart_resilience()
except Exception as _restart_error:
    print(f"[neyrobot-prod] selfie restart resilience bootstrap failed: {_restart_error!r}", flush=True)

__all__ = ["VERSION", "AI_SELFIE_VERSION"]
