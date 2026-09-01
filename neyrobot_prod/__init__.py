# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

AI-selfie activation is intentionally NOT performed from package import.  Historical
V247..V264 modules remain source history only until they are removed/migrated; package
initialization must never build a fallback chain as a side effect.  sitecustomize.py
installs the stable V246 Telegram/UX base and then exactly one final selfie owner:
V265.
"""

VERSION = "v265-dense68-single-owner-production-2026-09-01"
PRODUCTION_SELFIE_RUNTIME = "v265"

# Compatibility exports for code/tests that inspect historical acceptance flags.
V263_PRODUCTION_ACCEPTED = False
V264_PRODUCTION_ACCEPTED = False
V265_PRODUCTION_ACCEPTED = True

# Retouch is a separate UX feature, not an AI-selfie generation owner.  It may patch
# retouch helpers, but it must not install any historical selfie runtime or fallback.
try:
    from neyrobot_prod import retouch_v261_batch as _retouch_v261_module

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
    "VERSION",
    "PRODUCTION_SELFIE_RUNTIME",
    "V263_PRODUCTION_ACCEPTED",
    "V264_PRODUCTION_ACCEPTED",
    "V265_PRODUCTION_ACCEPTED",
]
