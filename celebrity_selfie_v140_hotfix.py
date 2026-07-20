# -*- coding: utf-8 -*-
"""Compatibility shim for the v140 scene-rescue overlay.

The production route remains v140, while the historical v139 module keeps its
own component version and its tests can still replace the scene factory.
"""
from __future__ import annotations

from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140

V139_COMPONENT_VERSION = "v139-two-stage-celebrity-selfie-2026-07-20"
_ORIGINAL_SCENE_FACTORY = v140._make_scene_candidates


async def _scene_factory_dispatch(mod: Any, scene: str, aspect: str, debug: dict[str, Any]):
    current = v139._make_scene_candidates
    if current is not _scene_factory_dispatch and current is not _ORIGINAL_SCENE_FACTORY:
        return await current(mod, scene, aspect, debug)
    return await _ORIGINAL_SCENE_FACTORY(mod, scene, aspect, debug)


def install() -> None:
    # Keep the historical component identifier stable. The public /version value
    # still comes from neyrobot_prod.VERSION and therefore reports v140.
    v139.VERSION = V139_COMPONENT_VERSION

    # Normal runtime calls dispatch -> original v140 provider adapter. Tests and
    # diagnostics may temporarily patch v139._make_scene_candidates and the
    # dispatcher will respect that replacement instead of bypassing it.
    v140._make_scene_candidates = _scene_factory_dispatch
    v139._make_scene_candidates = _scene_factory_dispatch


install()

__all__ = ["install", "_scene_factory_dispatch", "V139_COMPONENT_VERSION"]
