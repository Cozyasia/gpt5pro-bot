# -*- coding: utf-8 -*-
"""Current official OpenAI model policy for Neyro-Bot.

The policy is deliberately adaptive: it prefers the current GPT-5.6 family when
that family is visible to this API project, while the existing /v1/models based
resolver automatically falls back to GPT-5.2/GPT-5/GPT-5 mini during gradual
rollouts or account-specific availability limits.
"""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any

VERSION = "v115-current-model-policy-2026-07-18"
_INSTALLED = False

CURRENT_PRICES = {
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6": (5.00, 30.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5.4-mini": (0.75, 4.50),
}


def _upgrade_default(name: str, legacy: set[str], new_value: str) -> None:
    current = (os.environ.get(name) or "").strip()
    if not current or current in legacy:
        os.environ[name] = new_value


def _set_policy_environment() -> None:
    os.environ.setdefault("GENERAL_MODEL_BASIC", "gpt-5-mini")
    os.environ.setdefault("GENERAL_MODEL_PRO", "gpt-5-mini")
    os.environ.setdefault("GENERAL_MODEL_ULTIMATE", "gpt-5-mini")
    _upgrade_default("GENERAL_MODEL_COMPLEX_PRO", {"gpt-5"}, "gpt-5.6-luna")
    _upgrade_default("GENERAL_MODEL_COMPLEX_ULTIMATE", {"gpt-5"}, "gpt-5.6-terra")

    os.environ.setdefault("MEDICAL_EXTRACT_MODEL", "gpt-5-mini")
    os.environ.setdefault("MEDICAL_AUDIT_MODEL", "gpt-5-mini")
    os.environ.setdefault("MEDICAL_REASONING_MODEL_BASIC", "gpt-5-mini")
    _upgrade_default("MEDICAL_REASONING_MODEL_PRO", {"gpt-5"}, "gpt-5.6-luna")
    _upgrade_default("MEDICAL_REASONING_MODEL_ULTIMATE", {"gpt-5.2"}, "gpt-5.6-terra")


def _patch_medical_client(module: Any) -> None:
    with contextlib.suppress(Exception):
        module.PRICES.update(CURRENT_PRICES)
    with contextlib.suppress(Exception):
        module._NON_API_MODEL_PATTERNS = ()
    with contextlib.suppress(Exception):
        module._STABLE_BY_KIND = {
            "extract": [
                "gpt-5-mini", "gpt-5.4-mini", "gpt-5.6-luna",
                "gpt-4.1-mini", "gpt-4o-mini",
            ],
            "reason": [
                "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.2",
                "gpt-5.1", "gpt-5", "gpt-5-mini",
            ],
            "audit": [
                "gpt-5-mini", "gpt-5.4-mini", "gpt-5.6-luna",
                "gpt-4.1-mini",
            ],
        }


def _patch_general_router(module: Any) -> None:
    with contextlib.suppress(Exception):
        module.PRICES.update(CURRENT_PRICES)


def _install_medical_mode_v116() -> None:
    with contextlib.suppress(Exception):
        from medical_mode_v116 import install_async, install_builder_hook
        install_builder_hook()
        install_async()


def _install_medical_card_v117() -> None:
    with contextlib.suppress(Exception):
        from medical_card_v117_upsell import install_async
        install_async()


def _install_release_v118() -> None:
    with contextlib.suppress(Exception):
        from release_v118_quality import install_async
        install_async()


def _install_medical_v119() -> None:
    """Pin public medical handlers and the Medical Card menu after legacy overlays."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.medical_followup import install_async
        install_async()


def _install_credit_store_v201() -> None:
    """Install canonical package buttons before the monolith builds its handlers."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.credit_store_v201 import install_async
        install_async()


def _install_commercial_numbers_v201() -> None:
    """Overwrite stale Render credit figures and obsolete package prices."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.commercial_numbers_v201 import install_async
        install_async()


def _install_celebrity_selfie_v201() -> None:
    """Install persistent selfie routing and the hidden owner reference manager."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.celebrity_selfie import install_async
        install_async()


def _install_selfie_admin_v202() -> None:
    """Install the non-silent, multi-source owner/admin service menu."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.selfie_admin_v202 import install
        install()


def _install_celebrity_selfie_v203() -> None:
    """Own final generation with direct Gemini when a Google key is available."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.celebrity_selfie_v203 import install
        install()


def _install_celebrity_selfie_v204() -> None:
    """Prefer CometAPI Gemini with user selfie plus three hero references."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.celebrity_selfie_v204 import install
        install()


def _install_selfie_v204_lock() -> None:
    """Leave V204 as the final owner after all legacy patch workers stop."""
    with contextlib.suppress(Exception):
        from neyrobot_prod.selfie_v204_lock import install
        install()


def _install_selfie_runtime_v207() -> None:
    """Canonicalize generator, persistent storage and service commands."""
    try:
        from neyrobot_prod.selfie_runtime_v207 import install
        install()
    except Exception as exc:
        print(f"[neyrobot-prod] selfie runtime v207 warning: {type(exc).__name__}: {exc}")


def _install_selfie_v209() -> None:
    """Install V209 from the guaranteed main.py bootstrap after the V207 stack."""
    try:
        from neyrobot_prod.selfie_v209_canonical import install
        install()
    except Exception as exc:
        print(f"[neyrobot-prod] selfie canonical v209 warning: {type(exc).__name__}: {exc}")


def _install_selfie_v210() -> None:
    """Fix the V208 generator signature and serialize repeated scene taps."""
    try:
        from neyrobot_prod.selfie_v210_generation_guard import install
        install()
    except Exception as exc:
        print(f"[neyrobot-prod] selfie generation v210 warning: {type(exc).__name__}: {exc}")


def _install_selfie_v211() -> None:
    """Retry slow Telegram uploads without regenerating or double charging."""
    try:
        from neyrobot_prod.selfie_v211_delivery import install
        install()
    except Exception as exc:
        print(f"[neyrobot-prod] selfie delivery v211 warning: {type(exc).__name__}: {exc}")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _set_policy_environment()

    medical = sys.modules.get("medical_v111_client")
    if medical is not None:
        _patch_medical_client(medical)

    general = sys.modules.get("text_router_v114")
    if general is not None:
        _patch_general_router(general)

    _install_medical_mode_v116()
    _install_medical_card_v117()
    _install_release_v118()
    _install_medical_v119()
    _install_credit_store_v201()
    _install_commercial_numbers_v201()
    _install_celebrity_selfie_v201()
    _install_selfie_admin_v202()
    _install_celebrity_selfie_v203()
    _install_celebrity_selfie_v204()
    _install_selfie_v204_lock()
    _install_selfie_runtime_v207()
    _install_selfie_v209()
    _install_selfie_v210()
    _install_selfie_v211()
    _INSTALLED = True


__all__ = ["VERSION", "install"]
