# -*- coding: utf-8 -*-
"""Compatibility isolation for the v143 strict live overlay.

The Telegram engine stays on v143 while historical v139 module-level callables
and failure taxonomy remain stable for rollback diagnostics and regression tests.
"""
from __future__ import annotations

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import celebrity_selfie_v140_hotfix as v140_hotfix
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143


def install() -> None:
    # Restore the historical component surface. v140's dispatcher is the tested
    # compatibility implementation for the v139 scene-first component.
    v139.VERSION = v140_hotfix.V139_COMPONENT_VERSION
    v139._run_two_stage_generation = v140._run_v140_generation
    v139._failure_message = v143._ORIGINAL_FAILURE_MESSAGE

    # Reassert v143 only on the live runtime/Telegram ownership surfaces.
    selfie = v139.selfie
    selfie._run_v142_generation = v143._run_v143_generation
    selfie._run_v143_generation = v143._run_v143_generation
    selfie._generate = v142._generate
    selfie.engine._run_multi_reference_generation = v143._run_compat
    selfie.engine._generate = v142._generate
    selfie.engine._result_kb = v142._result_kb
    selfie.engine._diag = v143._diag
    v141._generate = v142._generate
    v141._result_kb = v142._result_kb


install()

__all__ = ["install"]
