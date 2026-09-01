# -*- coding: utf-8 -*-
"""Reproduce the removed production verifier execution context.

The heavy 1856x2304 probe runs inside a daemon thread using asyncio.run while the
foreground thread stays alive, matching the temporary verifier context that restarted
on Render. Optional resident baseline pressure is allocated before the daemon starts.
"""
from __future__ import annotations

import os
import runpy
import threading
import time

size = int(os.environ.get("V265_PROBE_BASELINE_BYTES", "0") or "0")
ballast = bytearray(size)
for offset in range(0, size, 4096):
    ballast[offset] = 1
print(
    f"AI_SELFIE_V265_STRICT_DAEMON baseline_bytes={size} resident=true daemon=true",
    flush=True,
)

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
