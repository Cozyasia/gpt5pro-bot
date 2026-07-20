# -*- coding: utf-8 -*-
"""Compatibility isolation for the live v139 Celebrity Selfie overlay.

v139 owns the live engine route.  The historical v136 module-level callable is
restored for rollback diagnostics and regression tests; the engine itself keeps
using v139.
"""
from __future__ import annotations

import celebrity_selfie_v136 as selfie
import celebrity_selfie_v139 as v139


def install() -> None:
    historical = getattr(selfie.v134, "_run_face_first_generation", None)
    if callable(historical) and historical is not v139._run_compat:
        selfie._run_v136_generation = historical

    # Reassert only the live runtime ownership after restoring the historical
    # module-level function above.
    selfie._run_v139_generation = v139._run_two_stage_generation
    selfie._generate = v139._generate
    selfie.engine._run_multi_reference_generation = v139._run_compat
    selfie.engine._generate = v139._generate
    selfie.engine._diag = v139._diag


install()

__all__ = ["install"]
