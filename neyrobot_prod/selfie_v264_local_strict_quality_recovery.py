# -*- coding: utf-8 -*-
"""V264 production routing correction for recoverable local quality failures.

The production guard historically sent every production-gate miss directly to an
external provider. That is too coarse for dense68/ocular cases: a candidate can pass
the legacy identity gate while missing only the tighter production geometry limits.
Those cases should spend the single allowed retry on V264 strict dense68 + ocular lock,
not on a provider that may change gaze/geometry and still fail the same gate.

Two-candidate contract is preserved:
* standard local V264 + strict local V264 when the standard remains legacy-valid;
* standard local V264 + isolated provider only when the standard fails the legacy
  identity/geometry gate catastrophically;
* preflight overscale/small-source rescue remains owned by the existing preflight
  overlay installed after this one.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v264_dense68_roi_production as v264
from neyrobot_prod import selfie_v264_production_quality_rescue as guard

VERSION = v264.VERSION
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    v264._log(message, *args)


def _second_route(*, legacy_passed: bool, production_passed: bool) -> str:
    if production_passed:
        return "strict_local_refinement"
    if legacy_passed:
        return "strict_local_recovery"
    return "isolated_provider_rescue"


def _set_runtime(runtime: Any, *, provider: str, path: str, metrics: dict[str, float]) -> None:
    runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = provider
    runtime.AI_SELFIE_LAST_IDENTITY_PATH = path
    runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(metrics)


async def _true_face_transfer_v264_quality_recovered(
    runtime: Any,
    stage1: bytes,
    source: bytes,
    source_photo_no: int,
):
    if int(source_photo_no) != 3:
        raise RuntimeError(f"V264 requires authoritative photo #3, got #{source_photo_no}")

    try:
        yunet_path = await v264.v253._ensure_yunet_model()
        dense_path, recognition_path = await v263._ensure_identity_models()

        standard, metrics, _ = v264._transfer_attempt_roi(
            bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=False
        )
        legacy_passed, legacy_failures = v263._quality_gate(metrics)
        production_passed, production_failures = guard._production_gate(metrics)
        refinement_reasons = (
            v264._visual_refinement_reasons(metrics)
            if production_passed and legacy_passed
            else []
        )
        route = _second_route(
            legacy_passed=bool(legacy_passed),
            production_passed=bool(production_passed),
        )
        _log(
            "AI_SELFIE_V264_RECOVERY_ROUTE standard_legacy=%s standard_production=%s route=%s "
            "identity=%.4f worst_eye=%.4f inner_nme=%.4f production_failures=%s",
            str(bool(legacy_passed)).lower(),
            str(bool(production_passed)).lower(),
            route,
            float(metrics.get("identity_similarity_cosine", 0.0)),
            max(float(metrics.get("left_eye_error", 1.0)), float(metrics.get("right_eye_error", 1.0))),
            float(metrics.get("inner_face_landmark_nme", 1.0)),
            "none" if not production_failures else "|".join(production_failures),
        )

        if production_passed and legacy_passed and not refinement_reasons:
            v263._log_quality(
                metrics,
                path="v264_standard",
                passed=True,
                strict_retry_triggered=False,
                strict_retry_success=False,
                failures=[],
            )
            _set_runtime(
                runtime,
                provider="opencv_dense68_roi_v264_standard",
                path="v264_standard",
                metrics=metrics,
            )
            return standard, "opencv_dense68_roi_identity_lock_standard"

        # A legacy-valid local candidate is not catastrophic. Keep the retry inside
        # the same deterministic dense68 + ocular-lock geometry instead of changing
        # algorithms/providers. This is also the normal refinement path.
        if legacy_passed:
            v263._log_quality(
                metrics,
                path="v264_standard",
                passed=True,
                strict_retry_triggered=True,
                strict_retry_success=False,
                failures=[],
            )
            retry_reasons = refinement_reasons or production_failures or ["production_gate"]
            _log(
                "AI_SELFIE_V264_STRICT_RETRY strict_retry_triggered=true route=%s reason=%s max_attempts=2",
                route,
                "|".join(retry_reasons),
            )
            strict, strict_metrics, _ = v264._transfer_attempt_roi(
                bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=True
            )
            strict_legacy_passed, strict_legacy_failures = v263._quality_gate(strict_metrics)
            strict_production_passed, strict_production_failures = guard._production_gate(strict_metrics)
            v263._log_quality(
                strict_metrics,
                path="v264_strict",
                passed=bool(strict_legacy_passed),
                strict_retry_triggered=True,
                strict_retry_success=bool(strict_legacy_passed and strict_production_passed),
                failures=[] if strict_legacy_passed else strict_legacy_failures,
            )

            if production_passed:
                prefer_strict = bool(
                    strict_legacy_passed
                    and strict_production_passed
                    and v264._prefer_strict_refinement(metrics, strict_metrics)
                )
                if prefer_strict:
                    _set_runtime(
                        runtime,
                        provider="opencv_dense68_roi_v264_refined_strict",
                        path="v264_refined_strict",
                        metrics=strict_metrics,
                    )
                    _log(
                        "AI_SELFIE_V264_RECOVERY_SELECT selected=strict mode=refinement "
                        "standard_identity=%.4f strict_identity=%.4f",
                        float(metrics.get("identity_similarity_cosine", 0.0)),
                        float(strict_metrics.get("identity_similarity_cosine", 0.0)),
                    )
                    return strict, "opencv_dense68_roi_identity_lock_refined_strict"

                _set_runtime(
                    runtime,
                    provider="opencv_dense68_roi_v264_standard_retained",
                    path="v264_standard_retained",
                    metrics=metrics,
                )
                _log(
                    "AI_SELFIE_V264_RECOVERY_SELECT selected=standard mode=refinement "
                    "strict_production=%s strict_failures=%s",
                    str(bool(strict_production_passed)).lower(),
                    "none" if not strict_production_failures else "|".join(strict_production_failures),
                )
                return standard, "opencv_dense68_roi_identity_lock_standard_retained"

            if strict_legacy_passed and strict_production_passed:
                _set_runtime(
                    runtime,
                    provider="opencv_dense68_roi_v264_strict_quality_recovery",
                    path="v264_strict_quality_recovery",
                    metrics=strict_metrics,
                )
                _log(
                    "AI_SELFIE_V264_RECOVERY_SELECT selected=strict mode=production_recovery "
                    "standard_failures=%s strict_identity=%.4f",
                    "|".join(production_failures) if production_failures else "production_gate",
                    float(strict_metrics.get("identity_similarity_cosine", 0.0)),
                )
                return strict, "opencv_dense68_roi_identity_lock_strict_quality_recovery"

            _log(
                "AI_SELFIE_V264_PRODUCTION_REJECT status=rejected after=local_strict_recovery "
                "delivery=blocked standard_failures=%s strict_failures=%s",
                "|".join(production_failures) if production_failures else "production_gate",
                "|".join(strict_production_failures or strict_legacy_failures) or "unknown",
            )
            raise RuntimeError("V264 production quality gate rejected PERSON-A after local strict recovery")

        # Catastrophic legacy-gate failure keeps the existing isolated provider rescue
        # as the second and final candidate.
        v263._log_quality(
            metrics,
            path="v264_standard",
            passed=False,
            strict_retry_triggered=True,
            strict_retry_success=False,
            failures=legacy_failures,
        )
        _log(
            "AI_SELFIE_V264_RESCUE_ROUTE status=triggered route=isolated_provider reason=%s max_attempts=2",
            "|".join(legacy_failures or production_failures) or "legacy_quality_gate",
        )
        rescue, provider = await guard._provider_rescue(runtime, stage1, source, source_photo_no)
        rescue_metrics = guard._evaluate_candidate(
            rescue, stage1, source, yunet_path, dense_path, recognition_path
        )
        rescue_passed, rescue_failures = guard._production_gate(rescue_metrics)
        rescue_legacy_passed, rescue_legacy_failures = v263._quality_gate(rescue_metrics)
        _log(
            "AI_SELFIE_V264_PRODUCTION_GATE path=provider_rescue status=%s provider=%s identity=%.4f "
            "worst_eye=%.4f failures=%s",
            "pass" if rescue_passed and rescue_legacy_passed else "fail",
            provider,
            float(rescue_metrics.get("identity_similarity_cosine", 0.0)),
            max(float(rescue_metrics.get("left_eye_error", 1.0)), float(rescue_metrics.get("right_eye_error", 1.0))),
            "none"
            if rescue_passed and rescue_legacy_passed
            else "|".join(rescue_failures or rescue_legacy_failures),
        )
        if rescue_passed and rescue_legacy_passed:
            _set_runtime(
                runtime,
                provider=provider,
                path="v264_provider_rescue",
                metrics=rescue_metrics,
            )
            return rescue, "provider_isolated_identity_rescue"

        raise RuntimeError("V264 production quality gate rejected PERSON-A after provider rescue")

    except Exception as exc:
        try:
            from neyrobot_prod.selfie_v263_runtime_safety import V263InfrastructureUnavailable
        except Exception:
            V263InfrastructureUnavailable = ()  # type: ignore[assignment,misc]
        if V263InfrastructureUnavailable and isinstance(exc, V263InfrastructureUnavailable):
            _log(
                "AI_SELFIE_V264_INFRA_FALLBACK status=fallback_v262 reason=%s:%s "
                "identity_gate_bypass=false rollback=v262",
                type(exc).__name__, str(exc)[:300],
            )
            _set_runtime(
                runtime,
                provider="opencv_v262_infrastructure_fallback",
                path="v262_degraded_infrastructure",
                metrics={},
            )
            return await v264.v262._true_face_transfer_v262(runtime, stage1, source, source_photo_no)
        raise


def install() -> None:
    global _INSTALLED
    v264._true_face_transfer_v264 = _true_face_transfer_v264_quality_recovered
    v264.enforce_runtime(bind_generate=True)
    _INSTALLED = True
    _log(
        "AI_SELFIE_V264_LOCAL_QUALITY_RECOVERY_INSTALL status=ok "
        "legacy_valid_retry=strict_dense68_ocular catastrophic_retry=isolated_provider "
        "max_attempts=2 person_b=pixel_locked"
    )


__all__ = [
    "VERSION",
    "install",
    "_second_route",
    "_true_face_transfer_v264_quality_recovered",
]
