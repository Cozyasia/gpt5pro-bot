# -*- coding: utf-8 -*-
"""Compatibility isolation for the v142 preserve-user live overlay.

The live Telegram engine stays on v142. Historical module-level contracts for
v139 and v141 are restored so rollback diagnostics and regression tests do not
silently execute the newest production pipeline.
"""
from __future__ import annotations

from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import celebrity_selfie_v140_hotfix as v140_hotfix
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142


async def _historical_v141_generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    """Reconstruct v141's public wrapper without taking live engine ownership."""
    if refinement:
        await v141._postprocess(update, context, "similarity")
        return
    await v141._ORIGINAL_GENERATE(update, context, refinement=False)
    session = v141._session(context)
    if session.get("state") == "result" and session.get("result_path"):
        v141._snapshot_accepted(session)


def install() -> None:
    # Restore historical component identifiers and public callables.
    v139.VERSION = v140_hotfix.V139_COMPONENT_VERSION
    v139._run_two_stage_generation = v140._run_v140_generation
    v139._generate = _historical_v141_generate
    v141._generate = _historical_v141_generate
    v141._result_kb = v142._ORIGINAL_V141_RESULT_KB

    # Reassert v142 only on the live engine/runtime surfaces.
    selfie = v139.selfie
    selfie._run_v142_generation = v142._run_v142_generation
    selfie._generate = v142._generate
    selfie.engine._run_multi_reference_generation = v142._run_compat
    selfie.engine._generate = v142._generate
    selfie.engine._result_kb = v142._result_kb
    selfie.engine._diag = v142._diag


install()

__all__ = ["install", "_historical_v141_generate"]
