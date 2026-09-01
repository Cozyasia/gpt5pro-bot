# -*- coding: utf-8 -*-
"""Run the V265 strict stability probe with persistent production-like memory pressure."""
from __future__ import annotations

import os
import runpy

size = int(os.environ.get("V265_PROBE_BASELINE_BYTES", "100663296") or "100663296")
# Keep these pages resident for the entire standard->strict run to emulate the
# long-lived Telegram/Gemini/main-process baseline that the isolated engine probe lacks.
ballast = bytearray(size)
for offset in range(0, size, 4096):
    ballast[offset] = 1
print(f"AI_SELFIE_V265_STRICT_PRESSURE baseline_bytes={size} resident=true", flush=True)
runpy.run_path("scripts/v265_strict_stability_probe.py", run_name="__main__")
