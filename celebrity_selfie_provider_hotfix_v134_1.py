# -*- coding: utf-8 -*-
"""Runtime provider hotfix for Celebrity Selfie v134.

Production diagnostics showed CometAPI returning HTTP 503/model_not_found for
``gemini-2-5-flash-image-preview``. The preview route was retired; this patch
normalises historical slugs, removes preview-only routes, and always places the
stable Gemini image endpoint first. OpenAI Images remains the second-provider
fallback in the existing v133/v134 pipeline.
"""
from __future__ import annotations

import os
from typing import Any

import celebrity_selfie_v133 as v133

PATCH_VERSION = "v134.1-stable-comet-image-model-2026-07-20"
STABLE_MODEL = "gemini-2.5-flash-image"


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _normalise_model(value: Any) -> str:
    model = str(value or "").strip()
    # Historical Render values used a non-canonical separator after "2".
    model = model.replace("gemini-2-5-", "gemini-2.5-")
    return model


def _configured_values(mod: Any) -> list[str]:
    values: list[str] = []
    explicit = str(os.environ.get("CELEBRITY_COMET_IMAGE_MODELS") or "").strip()
    if explicit:
        values.extend(part.strip() for part in explicit.split(",") if part.strip())
    primary = getattr(mod, "COMET_IMAGE_EDIT_MODEL", "")
    if primary:
        values.append(str(primary))
    fallback = getattr(mod, "COMET_IMAGE_EDIT_FALLBACK_MODELS", []) or []
    if isinstance(fallback, str):
        values.extend(part.strip() for part in fallback.split(",") if part.strip())
    else:
        values.extend(str(item) for item in fallback if str(item or "").strip())
    return values


def _comet_models(mod: Any) -> list[str]:
    """Return only deployable image-edit model IDs, stable model first."""
    allow_preview = _flag("CELEBRITY_ALLOW_PREVIEW_IMAGE_MODELS", False)
    result: list[str] = [STABLE_MODEL]
    for raw in _configured_values(mod):
        model = _normalise_model(raw)
        if not model:
            continue
        if "preview" in model.casefold() and not allow_preview:
            continue
        if model not in result:
            result.append(model)
    return result


def install() -> None:
    # _comet_scene_candidate resolves this symbol from the v133 module globals at
    # call time, so patching it here also affects the active v134 overlay.
    v133._comet_models = _comet_models
    v133.PROVIDER_PATCH_VERSION = PATCH_VERSION


install()

__all__ = [
    "PATCH_VERSION",
    "STABLE_MODEL",
    "_normalise_model",
    "_comet_models",
    "install",
]
