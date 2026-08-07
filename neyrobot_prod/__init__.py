# -*- coding: utf-8 -*-
"""Neyro-Bot production package."""

VERSION = "v255-scene-photo-face-target-quality-gate-2026-08-08"

try:
    from .selfie_v241_resilient_face_detection import install as _install_v241
    _install_v241()
except Exception as _v241_error:
    print(f"[neyrobot-prod] V241 detector bootstrap failed: {_v241_error!r}", flush=True)

try:
    from .selfie_v242_nonfatal_target_lock import install as _install_v242
    _install_v242()
except Exception as _v242_error:
    print(f"[neyrobot-prod] V242 target-lock bootstrap failed: {_v242_error!r}", flush=True)

try:
    from .selfie_v243_resilient_piapi_transport import install as _install_v243
    _install_v243()
except Exception as _v243_error:
    print(f"[neyrobot-prod] V243 PiAPI transport bootstrap failed: {_v243_error!r}", flush=True)

try:
    from .selfie_v244_transport_owner import install as _install_v244
    _install_v244()
except Exception as _v244_error:
    print(f"[neyrobot-prod] V244 transport-owner bootstrap failed: {_v244_error!r}", flush=True)

# V255 keeps V254/V252 photorealistic final integration active while the real
# V238 production route now performs scene-photo-aware framing plus a pre-PiAPI
# target geometry gate/retry. PiAPI remains the terminal identity provider.
try:
    from .selfie_v253_production_faceswap_quality import install as _install_v253
    _install_v253()
except Exception as _v253_error:
    print(f"[neyrobot-prod] V255 production Face Swap quality bootstrap failed: {_v253_error!r}", flush=True)

# Independent diagnostic remains available for controlled two-photo tests.
try:
    from .selfie_v246_faceswap_diag_bootstrap import install as _install_v246
    _install_v246()
except Exception as _v246_error:
    print(f"[neyrobot-prod] V255 Face Swap quality diagnostic bootstrap failed: {_v246_error!r}", flush=True)

__all__ = ["VERSION"]
