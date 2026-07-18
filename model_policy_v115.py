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
    # Values inserted by previous built-in defaults are upgraded. Any explicit
    # non-legacy operator override is preserved.
    if not current or current in legacy:
        os.environ[name] = new_value


def _set_policy_environment() -> None:
    # Ordinary chat stays cheap. Only complex paid requests are elevated.
    os.environ.setdefault("GENERAL_MODEL_BASIC", "gpt-5-mini")
    os.environ.setdefault("GENERAL_MODEL_PRO", "gpt-5-mini")
    os.environ.setdefault("GENERAL_MODEL_ULTIMATE", "gpt-5-mini")
    _upgrade_default("GENERAL_MODEL_COMPLEX_PRO", {"gpt-5"}, "gpt-5.6-luna")
    _upgrade_default("GENERAL_MODEL_COMPLEX_ULTIMATE", {"gpt-5"}, "gpt-5.6-terra")

    # Medical extraction and independent audit remain on the economical mini
    # route. Clinical reasoning receives the stronger model by subscription.
    os.environ.setdefault("MEDICAL_EXTRACT_MODEL", "gpt-5-mini")
    os.environ.setdefault("MEDICAL_AUDIT_MODEL", "gpt-5-mini")
    os.environ.setdefault("MEDICAL_REASONING_MODEL_BASIC", "gpt-5-mini")
    _upgrade_default("MEDICAL_REASONING_MODEL_PRO", {"gpt-5"}, "gpt-5.6-luna")
    _upgrade_default("MEDICAL_REASONING_MODEL_ULTIMATE", {"gpt-5.2"}, "gpt-5.6-terra")


def _patch_medical_client(module: Any) -> None:
    with contextlib.suppress(Exception):
        module.PRICES.update(CURRENT_PRICES)
    # The previous release rejected Sol/Terra/Luna because they had not yet
    # reached the public API. They are now official IDs.
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

    _INSTALLED = True


__all__ = ["VERSION", "install"]
