# -*- coding: utf-8 -*-
"""Temporary fail-closed guard for the unproven V265 strict second pass.

The V265 production owner, quality thresholds and production gate remain unchanged.
This guard only prevents the strict second pass from executing in production until
its runtime stability is proven independently. A hard-passing standard candidate is
returned without optional strict refinement; a hard-failing standard candidate still
fails closed when V265 attempts strict recovery.
"""
from __future__ import annotations

from typing import Any, Callable

from neyrobot_prod import dense68_engine_v265 as engine

_INSTALLED = False
_BASE_TRANSFER: Callable[..., Any] | None = None
_BASE_REFINEMENT_REASONS: Callable[..., Any] | None = None


def install() -> None:
    global _INSTALLED, _BASE_TRANSFER, _BASE_REFINEMENT_REASONS
    if _INSTALLED:
        return

    _BASE_TRANSFER = engine.transfer_attempt
    _BASE_REFINEMENT_REASONS = engine.visual_refinement_reasons

    def _guarded_transfer_attempt(*args: Any, strict: bool, **kwargs: Any):
        if bool(strict):
            raise RuntimeError(
                "V265 strict retry temporarily disabled: runtime stability not yet proven"
            )
        return _BASE_TRANSFER(*args, strict=False, **kwargs)

    def _guarded_refinement_reasons(metrics: dict[str, float]) -> list[str]:
        # A standard candidate that already passed the unchanged V265 hard gate must
        # not enter the unproven strict runtime path merely for optional refinement.
        return []

    engine.transfer_attempt = _guarded_transfer_attempt
    engine.visual_refinement_reasons = _guarded_refinement_reasons
    _INSTALLED = True
    print(
        "AI_SELFIE_V265_STRICT_SAFETY status=armed strict_enabled=false "
        "standard_gate_unchanged=true legacy_fallback=false",
        flush=True,
    )


__all__ = ["install"]
