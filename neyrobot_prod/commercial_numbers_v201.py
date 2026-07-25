# -*- coding: utf-8 -*-
"""Canonical commercial numbers for the v201 release.

Render may still contain historical values with one missing zero (20/120/350 and
100/300/700) or obsolete package prices.  This layer makes the public catalogue
and subscription cards deterministic unless the owner explicitly disables the
canonical lock with COMMERCIAL_NUMBERS_CANONICAL=0.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from typing import Any

VERSION = "v201-commercial-numbers-2026-07-25"
CANONICAL_PACKAGES = (("small", 1000, 990), ("mid", 3000, 2490), ("big", 7000, 4990))
CANONICAL_INCLUDED = {"start": 200, "pro": 1200, "ultimate": 3500}
_WORKER_STARTED = False


def _enabled() -> bool:
    return (os.environ.get("COMMERCIAL_NUMBERS_CANONICAL", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _patch_store() -> None:
    if not _enabled():
        return
    from neyrobot_prod import credit_store_v201 as store

    def catalog():
        return tuple(store.CreditPack(key, credits, rub) for key, credits, rub in CANONICAL_PACKAGES)

    store.catalog = catalog


def _rewrite_features(features: Any, credits: int) -> list[str]:
    rows = [str(item) for item in (features or [])]
    replacement = f"🪙 {credits} кредитов каждый месяц"
    for index, item in enumerate(rows):
        if "кредит" in item.lower() and "каждый месяц" in item.lower():
            rows[index] = replacement
            return rows
    rows.append(replacement)
    return rows


def patch_runtime(mod: Any) -> bool:
    if not _enabled():
        return True
    _patch_store()
    from neyrobot_prod import credit_store_v201 as store

    subscription = getattr(mod, "SUBSCRIPTION_CREDITS", None)
    if isinstance(subscription, dict):
        subscription.update(CANONICAL_INCLUDED)

    tiers = getattr(mod, "SUBS_TIERS", None)
    if isinstance(tiers, dict):
        for key, credits in CANONICAL_INCLUDED.items():
            tier = tiers.get(key)
            if isinstance(tier, dict):
                tier["credits"] = credits
                tier["features"] = _rewrite_features(tier.get("features"), credits)

    mod.CREDIT_PACKAGES_RUB = {credits: rub for _key, credits, rub in CANONICAL_PACKAGES}
    mod._credit_pack_resolve = store.resolve_pack
    mod.CREDIT_STORE_VERSION = store.VERSION
    mod.COMMERCIAL_NUMBERS_VERSION = VERSION
    return True


def install_async() -> None:
    global _WORKER_STARTED
    _patch_store()
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            mod = _runtime_module()
            if mod is None:
                time.sleep(0.1)
                continue
            try:
                if patch_runtime(mod):
                    stable += 1
                    if stable >= 300:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-commercial-numbers-v201").start()


__all__ = ["VERSION", "CANONICAL_PACKAGES", "CANONICAL_INCLUDED", "patch_runtime", "install_async"]
