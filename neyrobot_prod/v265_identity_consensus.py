# -*- coding: utf-8 -*-
"""Non-production V265 identity-fidelity analysis helpers.

This module is intentionally NOT imported by the production bootstrap or V265 runtime.
It captures the source-relative morphology veto discovered during analysis of a
MobileFace false-positive. The existing monotonic selector and production hard gate
remain unchanged on main.

The key distinction is between:
- face recognition: "could these images be the same identity class?"
- source fidelity: "does this generated face preserve this exact photo3 morphology?"

The latter is estimated from PIPNet-68 landmarks normalized only by eye-line
translation/rotation/interocular scale, then compared against a per-source
self-repeatability envelope. No absolute MobileFace cosine threshold is changed here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MorphologyVector:
    all68: float
    inner_face: float
    outline: float
    mouth: float
    central_chin: float


@dataclass(frozen=True)
class SourceSelfEnvelope:
    """Maximum source-vs-source deviation over deterministic benign perturbations."""

    all68: float
    inner_face: float
    outline: float
    mouth: float
    central_chin: float


@dataclass(frozen=True)
class FidelityDecision:
    passed: bool
    failures: tuple[str, ...]
    multiplier: float


def source_fidelity_decision(
    candidate: MorphologyVector,
    envelope: SourceSelfEnvelope,
    *,
    multiplier: float = 2.0,
) -> FidelityDecision:
    """Prototype source-fidelity veto.

    The threshold is relative to the *same source's measured landmark repeatability*,
    not a replacement cosine threshold. A candidate is rejected if its global/inner
    morphology exceeds the calibrated envelope or if at least two independent facial
    regions exceed that envelope. This is intentionally conservative and remains an
    analysis prototype until calibrated on enough visually accepted generated pairs.
    """
    if multiplier <= 1.0:
        raise ValueError("multiplier must leave calibration headroom")

    vals = {
        "all68": (candidate.all68, envelope.all68),
        "inner_face": (candidate.inner_face, envelope.inner_face),
        "outline": (candidate.outline, envelope.outline),
        "mouth": (candidate.mouth, envelope.mouth),
        "central_chin": (candidate.central_chin, envelope.central_chin),
    }
    exceeded = [
        name for name, (value, base) in vals.items()
        if float(value) > float(base) * float(multiplier)
    ]

    hard = []
    if "all68" in exceeded:
        hard.append("all68")
    if "inner_face" in exceeded:
        hard.append("inner_face")

    regional = [name for name in ("outline", "mouth", "central_chin") if name in exceeded]
    if len(regional) >= 2:
        hard.extend(regional)

    failures = tuple(dict.fromkeys(hard))
    return FidelityDecision(passed=not failures, failures=failures, multiplier=float(multiplier))


def recognition_consensus_summary(
    *,
    mobile_pipnet: float,
    mobile_yunet: float,
    arcface_pipnet: float,
    arcface_yunet: float,
) -> dict[str, float]:
    """Diagnostic-only multi-model/multi-alignment summary.

    No hard threshold is encoded: calibration showed that face-recognition cosine is
    not monotonic with exact visual likeness. The minimum is useful for diagnostics
    and future ROC calibration but is not a production acceptance rule by itself.
    """
    scores = {
        "mobile_pipnet": float(mobile_pipnet),
        "mobile_yunet": float(mobile_yunet),
        "arcface_pipnet": float(arcface_pipnet),
        "arcface_yunet": float(arcface_yunet),
    }
    scores["consensus_min"] = min(scores.values())
    scores["consensus_mean"] = sum(scores.values()) / 4.0
    return scores


__all__ = [
    "MorphologyVector",
    "SourceSelfEnvelope",
    "FidelityDecision",
    "source_fidelity_decision",
    "recognition_consensus_summary",
]
