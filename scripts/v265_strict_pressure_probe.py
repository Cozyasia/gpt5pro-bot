# -*- coding: utf-8 -*-
"""Run V265 strict stability through the production memory guard under pressure."""
from __future__ import annotations

import os
import runpy

os.environ["PROD_HARDENING_ENABLED"] = "0"
size = int(os.environ.get("V265_PROBE_BASELINE_BYTES", "100663296") or "100663296")
ballast = bytearray(size)
for offset in range(0, size, 4096):
    ballast[offset] = 1
print(f"AI_SELFIE_V265_STRICT_PRESSURE baseline_bytes={size} resident=true", flush=True)
from neyrobot_prod import v265_strict_runtime_safety as safety
safety.install()
runpy.run_path("scripts/v265_strict_stability_probe.py", run_name="__main__")
