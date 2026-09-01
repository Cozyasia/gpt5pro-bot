# -*- coding: utf-8 -*-
"""Run V265 strict through its memory guard under persistent pressure."""
from __future__ import annotations

import os
import runpy

os.environ["PROD_HARDENING_ENABLED"] = "0"
size = int(os.environ.get("V265_PROBE_BASELINE_BYTES", "100663296") or "100663296")
expect_block = str(os.environ.get("V265_EXPECT_MEMORY_BLOCK", "0") or "0").lower() in {"1", "true", "yes"}
ballast = bytearray(size)
for offset in range(0, size, 4096):
    ballast[offset] = 1
print(
    f"AI_SELFIE_V265_STRICT_PRESSURE baseline_bytes={size} resident=true expect_block={str(expect_block).lower()}",
    flush=True,
)
from neyrobot_prod import v265_strict_runtime_safety as safety
safety.install()
try:
    runpy.run_path("scripts/v265_strict_stability_probe.py", run_name="__main__")
except RuntimeError as exc:
    if expect_block and "insufficient container memory headroom" in str(exc):
        print(
            "AI_SELFIE_V265_STRICT_PRESSURE status=controlled_block process_restart=false "
            "strict_heavy_work_started=false",
            flush=True,
        )
    else:
        raise
else:
    if expect_block:
        raise RuntimeError("high-pressure strict probe unexpectedly bypassed memory safety block")
