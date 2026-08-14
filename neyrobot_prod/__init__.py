# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

V257 removes legacy AI Selfie production monkey-patch bootstraps from package
import. The stable secret_loader owner routes production generation to the
consolidated V257 runtime. The independent Face Swap diagnostic remains available.
V277 overlays the production terminal runtime with strict no-phone selfie framing
and a higher-fidelity terminal identity path.
"""

# Keep the package-level release version stable: the canonical /version owner and
# existing production tests intentionally treat this as a product release marker,
# not as the AI Selfie implementation version.
VERSION = "v206-selfie-command-routing-2026-07-25"
AI_SELFIE_VERSION = "v277-production-selfie-fidelity-2026-08-14"

# Keep the isolated provider diagnostic available for manual testing. It may use
# legacy transport helpers internally, but it is intentionally separate from the
# production AI Selfie route.
try:
    from .selfie_v246_faceswap_diag_bootstrap import install as _install_faceswap_diag
    _install_faceswap_diag()
except Exception as _diag_error:
    print(f"[neyrobot-prod] Face Swap diagnostic bootstrap failed: {_diag_error!r}", flush=True)

# V277 patches selfie_v257_consolidated_runtime in place. The guaranteed V257
# Telegram/billing owner later binds terminal.generate from that same module, so
# this patch survives the normal secret_loader bootstrap without introducing a
# second route owner.
try:
    from .selfie_v277_production_fidelity_patch import install as _install_selfie_v277
    _install_selfie_v277()
except Exception as _v277_error:
    print(f"[neyrobot-prod] V277 production selfie fidelity bootstrap failed: {_v277_error!r}", flush=True)

__all__ = ["VERSION", "AI_SELFIE_VERSION"]
