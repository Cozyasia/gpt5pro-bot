# -*- coding: utf-8 -*-
"""Run the production-size strict probe through the V265 memory safety guard."""
from __future__ import annotations

import os
import runpy

os.environ["PROD_HARDENING_ENABLED"] = "0"
from neyrobot_prod import v265_strict_runtime_safety as safety

safety.install()
runpy.run_path("scripts/v265_strict_stability_probe.py", run_name="__main__")
