# -*- coding: utf-8 -*-
"""Final bootstrap lock for Celebrity Selfie V204.

Historical selfie overlays keep patching the same symbol briefly during startup.
This lock runs longer than those workers, leaving V204 as the final owner without
modifying any other bot subsystem.
"""
from __future__ import annotations

import os
import threading
import time

VERSION = "v204-selfie-comet-lock-2026-07-25"
_STARTED = False


def install_async() -> None:
    global _STARTED
    from neyrobot_prod import celebrity_selfie_v204 as v204

    if v204._comet_key():
        os.environ["AI_SELFIE_PROVIDER"] = "comet"
    os.environ["CELEBRITY_SELFIE_DATA_DIR"] = "/data/celebrity_selfie"
    v204.patch()

    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(1800):
            try:
                v204.patch()
                mod = v204._runtime_module()
                if mod is not None and callable(getattr(mod, "_try_pay_then_do", None)):
                    stable += 1
                    # Legacy V203 stops after roughly 30 seconds. Keep V204 pinned
                    # for at least 90 seconds after the paid runtime appears.
                    if stable >= 900:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-selfie-v204-lock", daemon=True).start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "install_async", "install"]
