# -*- coding: utf-8 -*-
"""Production-grade acceptance gate and bounded provider rescue for V264.

The historical V263 gate is intentionally permissive enough for algorithmic smoke
validation. It is not a visual production acceptance threshold. This overlay adds a
stricter face-size-aware delivery gate. A standard candidate that is below production
quality does NOT receive another dense warp; its one retry is spent on the already
proven isolated provider path instead. Thus normal traffic remains pure V264 and a
bad Gemini scaffold cannot be delivered merely because the legacy smoke gate passed.

At most two candidate attempts are made: standard V264 + either strict V264 OR one
isolated provider rescue. PERSON-B is restored from stage1 after provider rescue and
final delivery remains PNG/document.
"""
from __future__ import annotations

import math
from typing import Any

from neyrobot_prod import selfie_v233_true_face_transfer as transfer_v233
from neyrobot_prod import selfie_v252_v3_png_quality as v252
from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v264_dense68_roi_production as v264

VERSION = v264.VERSION
_INSTALLED = False

# Large-face thresholds stay strict enough to block the known visibly broken
# 0.50-0.55 identity / 0.06+ eye-error case, but allow a tiny ocular-geometry
# measurement tolerance. A near-threshold candidate then follows V264's bounded
# local strict-refinement path instead of being needlessly diverted to a provider.
_LARGE_FACE_MIN = 500.0
_MEDIUM_FACE_MIN = 360.0
_LARGE_IDENTITY_MIN = 0.680
_MEDIUM_IDENTITY_MIN = 0.640
_SMALL_IDENTITY_MIN = 0.580
_LARGE_EYE_MAX = 0.050
_MEDIUM_EYE_MAX = 0.055
_SMALL_EYE_MAX = 0.070
_LARGE_INNER_NME_MAX = 0.050
_MEDIUM_INNER_NME_MAX = 0.060
_SMALL_INNER_NME_MAX = 0.070
_LARGE_ASYMMETRY_MAX = 0.030
_MEDIUM_ASYMMETRY_MAX = 0.040
_SMALL_ASYMMETRY_MAX = 0.060
_LARGE_INTEROCULAR_MAX = 0.045
_MEDIUM_INTEROCULAR_MAX = 0.050
_SMALL_INTEROCULAR_MAX = 0.065
_LARGE_AXIS_MAX = 0.050
_MEDIUM_AXIS_MAX = 0.060
_SMALL_AXIS_MAX = 0.075


def _log(message: str, *args: Any) -> None:
    v264._log(message, *args)


def _thresholds(face_short: float) -> dict[str, float]:
    face = float(face_short or 0.0)
    if face >= _LARGE_FACE_MIN:
        return {
            "identity": _LARGE_IDENTITY_MIN,
            "eye": _LARGE_EYE_MAX,
            "inner": _LARGE_INNER_NME_MAX,
            "asym": _LARGE_ASYMMETRY_MAX,
            "interocular": _LARGE_INTEROCULAR_MAX,
            "axis": _LARGE_AXIS_MAX,
        }
    if face >= _MEDIUM_FACE_MIN:
        return {
            "identity": _MEDIUM_IDENTITY_MIN,
            "eye": _MEDIUM_EYE_MAX,
            "inner": _MEDIUM_INNER_NME_MAX,
            "asym": _MEDIUM_ASYMMETRY_MAX,
            "interocular": _MEDIUM_INTEROCULAR_MAX,
            "axis": _MEDIUM_AXIS_MAX,
        }
    return {
        "identity": _SMALL_IDENTITY_MIN,
        "eye": _SMALL_EYE_MAX,
        "inner": _SMALL_INNER_NME_MAX,
        "asym": _SMALL_ASYMMETRY_MAX,
        "interocular": _SMALL_INTEROCULAR_MAX,
        "axis": _SMALL_AXIS_MAX,
    }


def _production_gate(metrics: dict[str, float]) -> tuple[bool, list[str]]:
    face_short = float(metrics.get("target_face_short", 0.0) or 0.0)
    limits = _thresholds(face_short)
    identity = float(metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    left_eye = float(metrics.get("left_eye_error", 1.0) or 1.0)
    right_eye = float(metrics.get("right_eye_error", 1.0) or 1.0)
    worst_eye = max(left_eye, right_eye)
    inner = float(metrics.get("inner_face_landmark_nme", 1.0) or 1.0)
    asym = float(metrics.get("eye_asymmetry_delta", 1.0) or 1.0)
    interocular = float(metrics.get("interocular_ratio_delta", 1.0) or 1.0)
    axis = float(metrics.get("nose_mouth_axis_delta", 1.0) or 1.0)

    values = (identity, worst_eye, inner, asym, interocular, axis)
    if not all(math.isfinite(v) for v in values):
        return False, ["nonfinite_metric"]

    failures: list[str] = []
    if identity < limits["identity"]:
        failures.append(f"identity={identity:.4f}<{limits['identity']:.4f}")
    if worst_eye > limits["eye"]:
        failures.append(f"eye_error={worst_eye:.4f}>{limits['eye']:.4f}")
    if inner > limits["inner"]:
        failures.append(f"inner_nme={inner:.4f}>{limits['inner']:.4f}")
    if asym > limits["asym"]:
        failures.append(f"eye_asymmetry={asym:.4f}>{limits['asym']:.4f}")
    if interocular > limits["interocular"]:
        failures.append(f"interocular={interocular:.4f}>{limits['interocular']:.4f}")
    if axis > limits["axis"]:
        failures.append(f"nose_mouth_axis={axis:.4f}>{limits['axis']:.4f}")
    return not failures, failures


def _normalize_provider_rescue(provider_bytes: bytes, stage1: bytes) -> bytes:
    """Normalize to stage1 dimensions and restore PERSON-B pixels before delivery."""
    import cv2

    target = v253._decode_bgr(bytes(stage1 or b""))
    candidate = v253._decode_bgr(bytes(provider_bytes or b""))
    th, tw = target.shape[:2]
    if candidate.shape[:2] != (th, tw):
        candidate = cv2.resize(candidate, (tw, th), interpolation=cv2.INTER_LANCZOS4)
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    candidate[:, firewall_x:] = target[:, firewall_x:]
    ok, encoded = cv2.imencode(".png", candidate, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V264 provider rescue PNG encode failed")
    return bytes(encoded.tobytes())


async def _provider_rescue(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int) -> tuple[bytes, str]:
    """Use the proven isolated PERSON-A provider route without shared-runtime mutation."""
    import hashlib

    target_crop, box = transfer_v233._left_person_crop(bytes(stage1 or b""))
    target_sha = hashlib.sha256(target_crop).hexdigest()[:12]
    swapped: bytes | None = None
    provider = ""
    errors: list[str] = []

    if bool(getattr(runtime, "SEGMIND_API_KEY", "")):
        try:
            candidate = await v252._segmind_v3_png(target_crop, source, target_index=0, source_index=0)
            if candidate and len(candidate) > 1024 and hashlib.sha256(bytes(candidate)).hexdigest()[:12] != target_sha:
                swapped = bytes(candidate)
                provider = "segmind_faceswap_v3_png_isolated_rescue"
            else:
                errors.append("segmind_v3:no_effect_or_empty")
        except Exception as exc:
            errors.append(f"segmind_v3:{type(exc).__name__}:{exc}")

    if swapped is None:
        piapi = getattr(runtime, "_piapi_faceswap", None)
        if callable(piapi) and bool(getattr(runtime, "PIAPI_API_KEY", "")):
            try:
                candidate = await piapi(target_crop, source, quality="fast", target_index=0, source_index=0)
                if candidate and len(candidate) > 1024 and hashlib.sha256(bytes(candidate)).hexdigest()[:12] != target_sha:
                    swapped = bytes(candidate)
                    provider = "piapi_faceswap_isolated_rescue"
                else:
                    errors.append("piapi:no_effect_or_empty")
            except Exception as exc:
                errors.append(f"piapi:{type(exc).__name__}:{exc}")

    if swapped is None:
        raise RuntimeError(
            "V264 provider rescue produced no usable PERSON-A transfer: "
            + (" | ".join(errors) if errors else "no provider configured")
        )

    merged = transfer_v233._merge_left_crop(bytes(stage1 or b""), swapped, box)
    merged = transfer_v233._ensure_full_hd(merged)
    normalized = _normalize_provider_rescue(merged, stage1)
    _log(
        "AI_SELFIE_V264_PROVIDER_RESCUE status=generated provider=%s isolated=true person_b_restored=true "
        "target_box=%s,%s,%s,%s output_bytes=%s",
        provider, box[0], box[1], box[2], box[3], len(normalized),
    )
    return normalized, provider


def _evaluate_candidate(candidate: bytes, stage1: bytes, source: bytes, yunet_path, dense_path, recognition_path) -> dict[str, float]:
    import numpy as np

    target = v253._decode_bgr(bytes(stage1 or b""))
    source_im = v253._decode_bgr(bytes(source or b""))
    final = v253._decode_bgr(bytes(candidate or b""))
    th, tw = target.shape[:2]
    if final.shape[:2] != (th, tw):
        raise RuntimeError(
            f"V264 rescue evaluation dimension mismatch final={final.shape[1]}x{final.shape[0]} target={tw}x{th}"
        )
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))

    source_bbox, source_pts5 = v253._yunet_face(source_im, yunet_path, label="source_photo3_v264_rescue")
    target_bbox, target_pts5 = v253._yunet_face(target[:, :firewall_x], yunet_path, label="target_person_a_v264_rescue")
    matrix, sim_rms = v263._similarity_transform(source_pts5, target_pts5)
    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = min(sfw, sfh)
    face_min = min(tfw, tfh)

    source_dense = v263._dense_landmarks_68(source_im, source_bbox, dense_path, label="source_photo3_rescue")
    target_dense = v263._dense_landmarks_68(target, target_bbox, dense_path, label="target_person_a_rescue")
    projected_dense = v264.v262._project_points(matrix, source_dense)
    desired_dense = v263._desired_identity_geometry(projected_dense, target_dense, face_min, strict=False)

    final_bbox, _ = v253._yunet_face(final[:, :firewall_x], yunet_path, label="final_person_a_v264_rescue")
    final_dense = v263._dense_landmarks_68(final, final_bbox, dense_path, label="final_person_a_rescue")
    source_embedding = v263._mobileface_embedding(source_im, source_dense, recognition_path)
    final_embedding = v263._mobileface_embedding(final, final_dense, recognition_path)
    metrics = dict(v263._quality_metrics(source_embedding, final_embedding, desired_dense, final_dense))
    metrics.update({
        "source_face_short": float(native_face_short),
        "target_face_short": float(face_min),
        "similarity_rms_normalized": float(sim_rms / max(face_min, 1.0)),
    })
    return metrics


async def _true_face_transfer_v264_guarded(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    if int(source_photo_no) != 3:
        raise RuntimeError(f"V264 requires authoritative photo #3, got #{source_photo_no}")

    try:
        yunet_path = await v253._ensure_yunet_model()
        dense_path, recognition_path = await v263._ensure_identity_models()

        # Attempt 1: stable production V264 standard.
        standard, metrics, _ = v264._transfer_attempt_roi(
            bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=False
        )
        legacy_passed, legacy_failures = v263._quality_gate(metrics)
        production_passed, production_failures = _production_gate(metrics)
        refinement_reasons = v264._visual_refinement_reasons(metrics) if production_passed and legacy_passed else []
        _log(
            "AI_SELFIE_V264_PRODUCTION_GATE path=standard status=%s identity=%.4f worst_eye=%.4f inner_nme=%.4f "
            "target_face_short=%.1f failures=%s",
            "pass" if production_passed else "fail",
            float(metrics.get("identity_similarity_cosine", 0.0)),
            max(float(metrics.get("left_eye_error", 1.0)), float(metrics.get("right_eye_error", 1.0))),
            float(metrics.get("inner_face_landmark_nme", 1.0)),
            float(metrics.get("target_face_short", 0.0)),
            "none" if not production_failures else "|".join(production_failures),
        )

        if production_passed and legacy_passed and not refinement_reasons:
            v263._log_quality(
                metrics, path="v264_standard", passed=True,
                strict_retry_triggered=False, strict_retry_success=False, failures=[]
            )
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_standard"
            runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_standard"
            runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(metrics)
            return standard, "opencv_dense68_roi_identity_lock_standard"

        if not production_passed or not legacy_passed:
            # Attempt 2 is provider rescue, not another local warp. This is the key
            # production rule for a badly scaffolded stage1 face.
            v263._log_quality(
                metrics, path="v264_standard", passed=legacy_passed,
                strict_retry_triggered=True, strict_retry_success=False,
                failures=[] if legacy_passed else legacy_failures,
            )
            _log(
                "AI_SELFIE_V264_RESCUE_ROUTE status=triggered route=isolated_provider reason=%s max_attempts=2",
                "|".join(production_failures or legacy_failures) or "production_gate",
            )
            rescue, provider = await _provider_rescue(runtime, stage1, source, source_photo_no)
            rescue_metrics = _evaluate_candidate(rescue, stage1, source, yunet_path, dense_path, recognition_path)
            rescue_passed, rescue_failures = _production_gate(rescue_metrics)
            _log(
                "AI_SELFIE_V264_PRODUCTION_GATE path=provider_rescue status=%s provider=%s identity=%.4f "
                "worst_eye=%.4f inner_nme=%.4f failures=%s",
                "pass" if rescue_passed else "fail", provider,
                float(rescue_metrics.get("identity_similarity_cosine", 0.0)),
                max(float(rescue_metrics.get("left_eye_error", 1.0)), float(rescue_metrics.get("right_eye_error", 1.0))),
                float(rescue_metrics.get("inner_face_landmark_nme", 1.0)),
                "none" if not rescue_failures else "|".join(rescue_failures),
            )
            if rescue_passed:
                runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = provider
                runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_provider_rescue"
                runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(rescue_metrics)
                return rescue, "provider_isolated_identity_rescue"

            _log(
                "AI_SELFIE_V264_PRODUCTION_REJECT status=rejected after=provider_rescue delivery=blocked "
                "standard_identity=%.4f rescue_identity=%.4f failures=%s",
                float(metrics.get("identity_similarity_cosine", 0.0)),
                float(rescue_metrics.get("identity_similarity_cosine", 0.0)),
                "|".join(rescue_failures) if rescue_failures else "unknown",
            )
            raise RuntimeError("V264 production quality gate rejected PERSON-A after provider rescue")

        # Standard is already production-grade. One optional strict local attempt may
        # improve identity, but it can never displace a safe standard with a candidate
        # that fails the production gate.
        v263._log_quality(
            metrics, path="v264_standard", passed=True,
            strict_retry_triggered=True, strict_retry_success=False, failures=[]
        )
        _log(
            "AI_SELFIE_V264_STRICT_RETRY strict_retry_triggered=true reason=visual_refinement:%s max_attempts=2",
            "|".join(refinement_reasons),
        )
        strict, strict_metrics, _ = v264._transfer_attempt_roi(
            bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=True
        )
        strict_legacy_passed, strict_legacy_failures = v263._quality_gate(strict_metrics)
        strict_production_passed, strict_production_failures = _production_gate(strict_metrics)
        v263._log_quality(
            strict_metrics, path="v264_strict", passed=strict_legacy_passed,
            strict_retry_triggered=True, strict_retry_success=strict_legacy_passed,
            failures=strict_legacy_failures,
        )
        prefer_strict = bool(
            strict_legacy_passed
            and strict_production_passed
            and v264._prefer_strict_refinement(metrics, strict_metrics)
        )
        selected_metrics = strict_metrics if prefer_strict else metrics
        selected = "strict" if prefer_strict else "standard"
        _log(
            "AI_SELFIE_V264_REFINEMENT_SELECT status=success selected=%s strict_legacy_passed=%s "
            "strict_production_passed=%s standard_identity=%.4f strict_identity=%.4f identity_gain=%.4f "
            "strict_production_failures=%s",
            selected, str(bool(strict_legacy_passed)).lower(), str(bool(strict_production_passed)).lower(),
            float(metrics.get("identity_similarity_cosine", 0.0)),
            float(strict_metrics.get("identity_similarity_cosine", 0.0)),
            float(strict_metrics.get("identity_similarity_cosine", 0.0)) - float(metrics.get("identity_similarity_cosine", 0.0)),
            "none" if not strict_production_failures else "|".join(strict_production_failures),
        )
        runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(selected_metrics)
        if prefer_strict:
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_refined_strict"
            runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_refined_strict"
            return strict, "opencv_dense68_roi_identity_lock_refined_strict"
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v264_standard_retained"
        runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_standard_retained"
        return standard, "opencv_dense68_roi_identity_lock_standard_retained"

    except Exception as exc:
        # Only concrete model/inference infrastructure failures are allowed to use
        # V262. Production-quality rejection is intentionally not hidden by fallback.
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
            runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v262_degraded_infrastructure"
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_v262_infrastructure_fallback"
            return await v264.v262._true_face_transfer_v262(runtime, stage1, source, source_photo_no)
        raise


def install() -> None:
    global _INSTALLED
    v264._true_face_transfer_v264 = _true_face_transfer_v264_guarded
    # Reassert the current final owner using V264's existing binding mechanism. The
    # bounded identity-core compositor, if installed, stays in place because this
    # overlay does not replace _structure_first_compose_roi.
    v264.enforce_runtime(bind_generate=True)
    _INSTALLED = True
    _log(
        "AI_SELFIE_V264_PRODUCTION_GUARD_INSTALL status=ok delivery_gate=production_grade "
        "bad_standard_retry=isolated_provider normal_retry=strict_dense max_attempts=2 "
        "person_b=pixel_restored provider_shared_state_mutation=false"
    )