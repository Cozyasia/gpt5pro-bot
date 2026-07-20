# -*- coding: utf-8 -*-
"""Post-load corrections for Celebrity Selfie v136.

Keep historical modules immutable for regression/rollback, while the live v122
engine remains routed through v136. Also use the canonical GenerateContent
``imageConfig`` REST field accepted by the current Gemini endpoint.
"""
from __future__ import annotations

from typing import Any

import celebrity_selfie_v136 as v136

V135 = "v135-celebrity-selfie-gemini3-native-identity-2026-07-20"
V134 = "v134-celebrity-selfie-face-first-soft-scene-2026-07-19"
V133 = "v133-celebrity-selfie-best-of-n-fallback-2026-07-19"
V132 = "v132-celebrity-selfie-validated-final-output-2026-07-19"


def _gemini_payload(prompt: str, refs: list[dict[str, Any]], *, aspect: str, image_size: str) -> dict[str, Any]:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}, *refs]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect,
                "imageSize": image_size,
            },
        },
    }


def _active(context: Any) -> bool:
    session = v136.wizard._session(context, create=False)
    data = v136.wizard._data(context)
    owner = str(session.get("owner") or "") if isinstance(session, dict) else ""
    return bool(data.get(v136.wizard._ACTIVE_KEY)) and bool(session) and owner in {v136.VERSION, V132}


def install() -> None:
    # v136 originally propagated its release label through every imported legacy
    # layer. Restore canonical historical labels so rollback tests and direct
    # module diagnostics remain truthful.
    v136.previous.VERSION = V135
    v136.v134.VERSION = V134
    v136.v133.VERSION = V133
    v136.base.VERSION = V132
    v136.wizard.VERSION = V132

    # Restore v135's own callable: historical tests patch it directly. The live
    # production engine still invokes v136 through engine._generate.
    v136.previous._run_native_generation = v136._LEGACY_RUN

    # Current Gemini GenerateContent REST schema accepts imageConfig here.
    v136._gemini_payload = _gemini_payload
    v136.wizard._active = _active

    # Reassert only the live engine ownership. Do not mutate historical methods.
    v136.engine._run_multi_reference_generation = v136._run_v136_generation
    v136.engine._generate = v136._generate
    v136.engine._diag = v136._diag


install()

__all__ = ["install", "_gemini_payload", "_active"]
