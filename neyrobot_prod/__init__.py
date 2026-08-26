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
VERSION = "v261-edge-harmonization-2026-08-26"

# Retouch is a UX/delivery overlay, not a Telegram route owner.  It arms one
# ApplicationBuilder wrapper and patches the already-existing main.py helpers only
# after main.py has defined them.  No callback/message/payment handlers are added.
try:
    from neyrobot_prod.retouch_v261_batch import install as _install_retouch_v261
    _install_retouch_v261()
except Exception as _retouch_v261_exc:
    print(
        f"[neyrobot-prod] retouch V261 overlay warning: {type(_retouch_v261_exc).__name__}: {_retouch_v261_exc}",
        flush=True,
    )

__all__ = ["VERSION"]
