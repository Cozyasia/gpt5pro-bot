# -*- coding: utf-8 -*-
"""V244 runtime owner for the terminal PiAPI face-swap transport.

V239 continuously rebinds the public Celebrity Selfie route. This owner mirrors
that behavior for the low-level PiAPI function so no late legacy import can
restore the previous one-shot HTTP transport.
"""
from __future__ import annotations

import contextlib
import threading
import time

VERSION = "v244-terminal-piapi-transport-owner-2026-08-06"
_STARTED = False


def bind() -> bool:
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as v243

    return bool(v243.install())


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
            time.sleep(0.1)

    threading.Thread(
        target=worker,
        daemon=True,
        name="neyrobot-selfie-v244-piapi-owner",
    ).start()
    print(f"[neyrobot-prod] V244 terminal PiAPI transport owner installed version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "bind", "install"]
