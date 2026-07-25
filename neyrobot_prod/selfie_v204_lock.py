# -*- coding: utf-8 -*-
"""Final bootstrap lock for Celebrity Selfie V204 + persistent V205 storage.

Historical selfie overlays keep patching the same symbols briefly during startup.
This lock keeps the working Comet multi-reference route while leaving V205 as the
final owner of character storage, catalogue and admin operations.
"""
from __future__ import annotations

import os
import threading
import time

VERSION = "v205-selfie-persistent-lock-2026-07-25"
_STARTED = False


def install_async() -> None:
    global _STARTED
    from neyrobot_prod import celebrity_selfie_v204 as v204
    from neyrobot_prod import selfie_storage_v205 as v205

    if v204._comet_key():
        os.environ["AI_SELFIE_PROVIDER"] = "comet"
    os.environ["CELEBRITY_SELFIE_DATA_DIR"] = "/data/celebrity_selfie"
    v204.patch()
    v205.install_async()

    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(2400):
            try:
                # Preserve the proven V204 generator, then re-pin V205 storage.
                v204.patch()
                v205.patch()
                mod = v204._runtime_module()
                if mod is not None and callable(getattr(mod, "_try_pay_then_do", None)):
                    stable += 1
                    if stable >= 1200:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-selfie-v205-lock", daemon=True).start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "install_async", "install"]
