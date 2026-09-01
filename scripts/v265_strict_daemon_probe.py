# -*- coding: utf-8 -*-
"""Run V265 strict through the production safety guard in verifier-like daemon context."""
from __future__ import annotations

import os
import runpy
import threading
import time

os.environ["PROD_HARDENING_ENABLED"] = "0"
size = int(os.environ.get("V265_PROBE_BASELINE_BYTES", "0") or "0")
ballast = bytearray(size)
for offset in range(0, size, 4096):
    ballast[offset] = 1
print(
    f"AI_SELFIE_V265_STRICT_DAEMON baseline_bytes={size} resident=true daemon=true",
    flush=True,
)
from neyrobot_prod import v265_strict_runtime_safety as safety
safety.install()

finished = threading.Event()
error: list[BaseException] = []


def worker() -> None:
    try:
        runpy.run_path("scripts/v265_strict_stability_probe.py", run_name="__main__")
    except BaseException as exc:
        error.append(exc)
    finally:
        finished.set()


thread = threading.Thread(target=worker, name="v265-strict-daemon-probe", daemon=True)
thread.start()
started = time.monotonic()
while not finished.wait(0.2):
    if time.monotonic() - started > 180.0:
        raise RuntimeError("daemon strict probe timed out")
if error:
    raise error[0]
print("AI_SELFIE_V265_STRICT_DAEMON status=complete process_restart=false", flush=True)
