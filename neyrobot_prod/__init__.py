# -*- coding: utf-8 -*-
"""Neyro-Bot production package.

AI-selfie generation has one production owner: V265. Historical selfie modules are
not chained from package import and are never used as recovery routes in production.
The existing sitecustomize bootstrap still asks V246 to install because V246 owns
useful Telegram UX/error/builder plumbing; in production that entrypoint is redirected
below to initialize only the V246 base primitives and then install V265. Crucially,
V246's historical successor chain is never executed.
"""
from __future__ import annotations

import os

VERSION = "v265-dense68-single-owner-production-2026-09-01"
PRODUCTION_SELFIE_RUNTIME = "v265"
V263_PRODUCTION_ACCEPTED = False
V264_PRODUCTION_ACCEPTED = False
V265_PRODUCTION_ACCEPTED = True


def _production_hardening_enabled() -> bool:
    return str(os.environ.get("PROD_HARDENING_ENABLED", "1") or "1").strip().lower() not in {
        "0", "false", "no", "off"
    }


# Production compatibility bootstrap: V246 base -> V265, with successors cut.
# CI sets PROD_HARDENING_ENABLED=0 so historical unit tests can exercise their own
# isolated versions without V265 intentionally replacing their installers.
if _production_hardening_enabled():
    try:
        from neyrobot_prod import selfie_v246_quality_hardlock as _v246_bootstrap

        def _install_v265_from_v246_entrypoint() -> None:
            if not bool(getattr(_v246_bootstrap, "_INSTALLED", False)):
                _v246_bootstrap._install_process_error_filter()
                _v246_bootstrap.v245.install()
                _v246_bootstrap._install_final_builder_hook()
                _v246_bootstrap.enforce_runtime(bind_generate=True)
                _v246_bootstrap._INSTALLED = True
            from neyrobot_prod.selfie_v265_single_owner import install as _install_v265
            _install_v265()

        # The function imported by sitecustomize at its existing V246 bootstrap point
        # now initializes only the UX base and V265; historical successors are absent.
        _v246_bootstrap.install = _install_v265_from_v246_entrypoint
    except Exception as _bootstrap_patch_exc:
        print(
            f"[neyrobot-prod] V265 bootstrap patch warning: {type(_bootstrap_patch_exc).__name__}: {_bootstrap_patch_exc}",
            flush=True,
        )

# Retouch is a separate UX feature, not an AI-selfie generation owner.
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

# TEMPORARY one-shot production verifier. It owns no handlers/runtime bindings and
# claims a persistent /data sentinel before fixture/model/Gemini/image work.
if _production_hardening_enabled():
    try:
        from neyrobot_prod.v265_production_verifier import start_once as _start_v265_production_verifier
        _start_v265_production_verifier()
    except Exception as _v265_verify_exc:
        print(
            f"[neyrobot-prod] V265 temporary verifier warning: {type(_v265_verify_exc).__name__}: {_v265_verify_exc}",
            flush=True,
        )

__all__ = [
    "VERSION",
    "PRODUCTION_SELFIE_RUNTIME",
    "V263_PRODUCTION_ACCEPTED",
    "V264_PRODUCTION_ACCEPTED",
    "V265_PRODUCTION_ACCEPTED",
]
