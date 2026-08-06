# -*- coding: utf-8 -*-
"""Neyro-Bot production package."""

VERSION = "v244-terminal-piapi-transport-owner-2026-08-06"

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

# V239 re-applies the generation route after package import. Keep the resilient
# low-level PiAPI transport owned as well, so it cannot be replaced by a late
# legacy bootstrap and silently revert to one-shot HTTP behavior.
try:
    from .selfie_v244_transport_owner import install as _install_v244
    _install_v244()
except Exception as _v244_error:
    print(f"[neyrobot-prod] V244 transport-owner bootstrap failed: {_v244_error!r}", flush=True)

__all__ = ["VERSION"]
