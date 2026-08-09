# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

V257 removes legacy AI Selfie production monkey-patch bootstraps from package
import. The stable secret_loader owner routes production generation to the
consolidated V257 runtime. The independent Face Swap diagnostic remains available
and does not own production AI Selfie generation.
"""

VERSION = "v257-consolidated-ai-selfie-faceswap-2026-08-09"

# Keep the isolated provider diagnostic available for manual testing. It may use
# legacy transport helpers internally, but it is intentionally separate from the
# V257 production AI Selfie route.
try:
    from .selfie_v246_faceswap_diag_bootstrap import install as _install_faceswap_diag
    _install_faceswap_diag()
except Exception as _diag_error:
    print(f"[neyrobot-prod] V257 Face Swap diagnostic bootstrap failed: {_diag_error!r}", flush=True)

__all__ = ["VERSION"]
