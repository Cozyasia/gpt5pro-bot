# -*- coding: utf-8 -*-
"""V244 runtime owner for the terminal face-transfer transport.

The owner binds the resilient PiAPI provider and then the deterministic literal
photo-3 fallback. It checks periodically without hammering imports or logs.
"""
from __future__ import annotations

import contextlib
import threading
import time

VERSION = "v244-terminal-transfer-owner-v245-2026-08-06"
_STARTED = False


def bind() -> bool:
    from neyrobot_prod import selfie_v245_literal_face_fallback as v245

    return bool(v245.install())


def install() -> bool:
    global _STARTED
    bind()
    if _STARTED:
        return True
    _STARTED = True

    def worker() -> None:
        while True:
            with contextlib.suppress(Exception):
                bind()
            time.sleep(2.0)

    threading.Thread(
        target=worker,
        daemon=True,
        name="neyrobot-selfie-v244-transfer-owner",
    ).start()
    print(f"[neyrobot-prod] V244 terminal transfer owner installed version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "bind", "install"]
