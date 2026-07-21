# -*- coding: utf-8 -*-
"""Compatibility isolation for the v143 strict live overlay.

The Telegram engine stays on v143 while historical v139/v141/v142 module-level
callables and regression-test contracts remain stable.
"""
from __future__ import annotations

from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import celebrity_selfie_v140_hotfix as v140_hotfix
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143


async def _historical_v142_prepare_user_cutout(
    mod: Any,
    raw: bytes,
    debug: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    result = await v143._prepare_user_cutout(mod, raw, debug, label)
    cutouts = debug.get("cutouts") or []
    if cutouts:
        cutouts[-1]["pixel_policy"] = "source_pixels_only"
    return result


def _historical_v142_composite_user(
    scene_raw: bytes,
    cutout_info: dict[str, Any],
    variant: int,
):
    raw, metadata = v143._composite_user(scene_raw, cutout_info, variant)
    metadata["user_pixel_policy"] = "source_pixels_preserved_no_generation"
    return raw, metadata


def install() -> None:
    # Restore the historical v139 component surface. v140's dispatcher is the
    # tested compatibility implementation for that scene-first component.
    v139.VERSION = v140_hotfix.V139_COMPONENT_VERSION
    v139._run_two_stage_generation = v140._run_v140_generation
    v139._failure_message = v143._ORIGINAL_FAILURE_MESSAGE

    # Preserve public historical contracts used by rollback diagnostics/tests.
    v141._result_kb = v142._ORIGINAL_V141_RESULT_KB
    v142._prepare_user_cutout = _historical_v142_prepare_user_cutout
    v142._composite_user = _historical_v142_composite_user

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


install()

__all__ = [
    "install",
    "_historical_v142_prepare_user_cutout",
    "_historical_v142_composite_user",
]
