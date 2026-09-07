# -*- coding: utf-8 -*-
"""V265 single production owner for AI-selfie generation.

There is exactly one PERSON-A identity-transfer algorithm in this runtime: the local
ROI-only 68-landmark engine in :mod:`dense68_engine_v265`. Historical V247..V264
modules are not installed and are not recovery routes.

Contract:
- Gemini owns the scene and PERSON-B; the user crop owns PERSON-A age/head/hair and
  expression scaffold.
- photo #3 is the only PERSON-A identity source.
- YuNet + PIPNet-68 + MobileFace drive the local transfer and quality checks.
- one standard local candidate and at most one strict local candidate are allowed.
- no Segmind/PiAPI rescue, no V262 rollback, no alternate compositor, no compressed
  delivery fallback. Any infrastructure/algorithm failure fails closed.
- V265 production_gate is the sole ACCEPT/REJECT decision gate. V263 is utility-only.
- natural eye asymmetry is a refinement/ranking signal, not a hard rejection metric.
  Hard delivery checks cover identity, eye landmark error, inner-face NME,
  interocular ratio and nose/mouth axis.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import math
from typing import Any, Callable

from neyrobot_prod import dense68_engine_v265 as engine
from neyrobot_prod import selfie_v241_authoritative_runtime as v241
from neyrobot_prod import selfie_v242_expression_lock as v242
from neyrobot_prod import selfie_v246_quality_hardlock as v246
from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v263_dense_identity_lock as v263

VERSION = engine.VERSION
_INSTALLED = False
_BUILDER_HOOKED = False
_BASE_V246_ENFORCE: Callable[..., Any] | None = None

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
_LARGE_INTEROCULAR_MAX = 0.045
_MEDIUM_INTEROCULAR_MAX = 0.050
_SMALL_INTEROCULAR_MAX = 0.065
_LARGE_AXIS_MAX = 0.050
_MEDIUM_AXIS_MAX = 0.060
_SMALL_AXIS_MAX = 0.075


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


def _metric(metrics: dict[str, float], key: str, default: float) -> float:
    """Read a metric without treating a valid 0.0 measurement as missing."""
    value = metrics.get(key, default)
    if value is None:
        value = default
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _thresholds(face_short: float) -> dict[str, float]:
    face = float(face_short)
    if face >= _LARGE_FACE_MIN:
        return {
            "identity": _LARGE_IDENTITY_MIN,
            "eye": _LARGE_EYE_MAX,
            "inner": _LARGE_INNER_NME_MAX,
            "interocular": _LARGE_INTEROCULAR_MAX,
            "axis": _LARGE_AXIS_MAX,
        }
    if face >= _MEDIUM_FACE_MIN:
        return {
            "identity": _MEDIUM_IDENTITY_MIN,
            "eye": _MEDIUM_EYE_MAX,
            "inner": _MEDIUM_INNER_NME_MAX,
            "interocular": _MEDIUM_INTEROCULAR_MAX,
            "axis": _MEDIUM_AXIS_MAX,
        }
    return {
        "identity": _SMALL_IDENTITY_MIN,
        "eye": _SMALL_EYE_MAX,
        "inner": _SMALL_INNER_NME_MAX,
        "interocular": _SMALL_INTEROCULAR_MAX,
        "axis": _SMALL_AXIS_MAX,
    }


def production_gate(metrics: dict[str, float]) -> tuple[bool, list[str]]:
    """Sole V265 hard delivery gate. Natural eye asymmetry is not a blocker."""
    face_short = _metric(metrics, "target_face_short", 0.0)
    limits = _thresholds(face_short)
    identity = _metric(metrics, "identity_similarity_cosine", 0.0)
    left_eye = _metric(metrics, "left_eye_error", 1.0)
    right_eye = _metric(metrics, "right_eye_error", 1.0)
    worst_eye = max(left_eye, right_eye)
    inner = _metric(metrics, "inner_face_landmark_nme", 1.0)
    interocular = _metric(metrics, "interocular_ratio_delta", 1.0)
    axis = _metric(metrics, "nose_mouth_axis_delta", 1.0)
    asym = _metric(metrics, "eye_asymmetry_delta", 0.0)

    if not all(math.isfinite(v) for v in (face_short, identity, worst_eye, inner, interocular, axis, asym)):
        return False, ["nonfinite_metric"]

    failures: list[str] = []
    if identity < limits["identity"]:
        failures.append(f"identity={identity:.4f}<{limits['identity']:.4f}")
    if worst_eye > limits["eye"]:
        failures.append(f"eye_error={worst_eye:.4f}>{limits['eye']:.4f}")
    if inner > limits["inner"]:
        failures.append(f"inner_nme={inner:.4f}>{limits['inner']:.4f}")
    if interocular > limits["interocular"]:
        failures.append(f"interocular={interocular:.4f}>{limits['interocular']:.4f}")
    if axis > limits["axis"]:
        failures.append(f"nose_mouth_axis={axis:.4f}>{limits['axis']:.4f}")
    return not failures, failures


def _set_runtime_result(runtime: Any, *, path: str, metrics: dict[str, float]) -> None:
    runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_roi_v265"
    runtime.AI_SELFIE_LAST_IDENTITY_PATH = path
    runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(metrics)


def _quality_log(path: str, metrics: dict[str, float], hard_passed: bool, failures: list[str]) -> None:
    _log(
        "AI_SELFIE_V265_QUALITY path=%s status=%s identity=%.4f worst_eye=%.4f inner_nme=%.4f "
        "interocular=%.4f axis=%.4f eye_asymmetry=%.4f asymmetry_hard_gate=false failures=%s",
        path,
        "pass" if hard_passed else "fail",
        _metric(metrics, "identity_similarity_cosine", 0.0),
        max(_metric(metrics, "left_eye_error", 1.0), _metric(metrics, "right_eye_error", 1.0)),
        _metric(metrics, "inner_face_landmark_nme", 1.0),
        _metric(metrics, "interocular_ratio_delta", 1.0),
        _metric(metrics, "nose_mouth_axis_delta", 1.0),
        _metric(metrics, "eye_asymmetry_delta", 0.0),
        "none" if not failures else "|".join(failures),
    )


_MONOTONIC_EPS = 1.0e-6


def _process_identity() -> tuple[int, str]:
    import os

    pid = int(os.getpid())
    host = str(os.environ.get("RENDER_INSTANCE_ID") or os.environ.get("HOSTNAME") or "unknown")
    return pid, host


def _metric_block_log(path: str, phase: str, metrics: dict[str, float], hard_passed: bool, failures: list[str]) -> None:
    pid, host = _process_identity()
    _log(
        "AI_SELFIE_V265_METRICS path=%s phase=%s identity_similarity_cosine=%.6f "
        "left_eye_error=%.6f right_eye_error=%.6f worst_eye=%.6f eye_asymmetry=%.6f "
        "interocular_ratio_delta=%.6f nose_mouth_axis_delta=%.6f inner_face_landmark_nme=%.6f "
        "hard_gate=%s failures=%s person_b=pixel_locked no_neck=true independent_eye_patch=false "
        "same_dense68_engine=true pid=%s host=%s",
        path,
        phase,
        _metric(metrics, "identity_similarity_cosine", 0.0),
        _metric(metrics, "left_eye_error", 1.0),
        _metric(metrics, "right_eye_error", 1.0),
        max(_metric(metrics, "left_eye_error", 1.0), _metric(metrics, "right_eye_error", 1.0)),
        _metric(metrics, "eye_asymmetry_delta", 0.0),
        _metric(metrics, "interocular_ratio_delta", 1.0),
        _metric(metrics, "nose_mouth_axis_delta", 1.0),
        _metric(metrics, "inner_face_landmark_nme", 1.0),
        "PASS" if hard_passed else "FAIL",
        "none" if not failures else "|".join(failures),
        pid,
        host,
    )


def _ocular_monotonic_decision(
    pre_metrics: dict[str, float],
    post_metrics: dict[str, float],
) -> tuple[bool, list[str]]:
    """Return whether post-ocular is a non-destructive improvement of one V265 candidate."""
    pre_hard, _ = production_gate(pre_metrics)
    post_hard, _ = production_gate(post_metrics)
    regressions: list[str] = []

    pre_identity = _metric(pre_metrics, "identity_similarity_cosine", 0.0)
    post_identity = _metric(post_metrics, "identity_similarity_cosine", 0.0)
    if post_identity + _MONOTONIC_EPS < pre_identity:
        regressions.append(f"identity={post_identity:.6f}<{pre_identity:.6f}")

    for key in (
        "left_eye_error",
        "right_eye_error",
        "eye_asymmetry_delta",
        "interocular_ratio_delta",
        "nose_mouth_axis_delta",
        "inner_face_landmark_nme",
    ):
        before = _metric(pre_metrics, key, 1.0 if key != "eye_asymmetry_delta" else 0.0)
        after = _metric(post_metrics, key, 1.0 if key != "eye_asymmetry_delta" else 0.0)
        if after > before + _MONOTONIC_EPS:
            regressions.append(f"{key}={after:.6f}>{before:.6f}")

    if pre_hard and not post_hard:
        regressions.append("hard_pass_to_fail")

    if regressions:
        return False, regressions

    improvements: list[str] = []
    if post_identity > pre_identity + _MONOTONIC_EPS:
        improvements.append("identity")
    for key in (
        "left_eye_error",
        "right_eye_error",
        "eye_asymmetry_delta",
        "interocular_ratio_delta",
        "nose_mouth_axis_delta",
        "inner_face_landmark_nme",
    ):
        before = _metric(pre_metrics, key, 1.0 if key != "eye_asymmetry_delta" else 0.0)
        after = _metric(post_metrics, key, 1.0 if key != "eye_asymmetry_delta" else 0.0)
        if after + _MONOTONIC_EPS < before:
            improvements.append(key)
    if post_hard and not pre_hard:
        improvements.append("hard_fail_to_pass")

    # No measurable benefit means there is no reason to replace the original candidate.
    if not improvements:
        return False, ["no_measurable_improvement"]
    return True, improvements


def _evaluate_candidate(path: str, phase: str, metrics: dict[str, float]) -> tuple[bool, list[str]]:
    hard, failures = production_gate(metrics)
    _metric_block_log(path, phase, metrics, hard, failures)
    return hard, failures


def _select_ocular_candidate(
    path: str,
    pre_output: bytes,
    pre_metrics: dict[str, float],
    post_output: bytes,
    post_metrics: dict[str, float],
) -> tuple[bytes, dict[str, float], str, bool, list[str]]:
    pre_hard, pre_failures = _evaluate_candidate(path, "pre_ocular", pre_metrics)
    post_hard, post_failures = _evaluate_candidate(path, "post_ocular", post_metrics)
    accept_post, decision = _ocular_monotonic_decision(pre_metrics, post_metrics)
    if accept_post:
        _log(
            "AI_SELFIE_V265_OCULAR_SELECT path=%s selected=post_ocular reason=%s pre_hard=%s post_hard=%s",
            path,
            "|".join(decision),
            "PASS" if pre_hard else "FAIL",
            "PASS" if post_hard else "FAIL",
        )
        return bytes(post_output), dict(post_metrics), "post_ocular", post_hard, post_failures
    _log(
        "AI_SELFIE_V265_OCULAR_SELECT path=%s selected=pre_ocular reason=discard_destructive_refinement:%s "
        "pre_hard=%s post_hard=%s",
        path,
        "|".join(decision),
        "PASS" if pre_hard else "FAIL",
        "PASS" if post_hard else "FAIL",
    )
    return bytes(pre_output), dict(pre_metrics), "pre_ocular", pre_hard, pre_failures


def _final_candidate_decision(
    standard_hard: bool,
    standard_metrics: dict[str, float],
    strict_hard: bool,
    strict_metrics: dict[str, float],
) -> str:
    """Choose the best valid V265 candidate; strict never wins merely by running last."""
    if standard_hard and strict_hard:
        return "strict" if engine.prefer_strict_refinement(standard_metrics, strict_metrics) else "standard"
    if strict_hard:
        return "strict"
    if standard_hard:
        return "standard"
    return "reject"


async def _true_face_transfer_v265(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    """Two same-engine dense68 attempts maximum with monotonic ocular/strict selection."""
    if int(source_photo_no) != 3:
        raise RuntimeError(f"V265 requires authoritative photo #3, got #{source_photo_no}")

    request_pid, request_host = _process_identity()
    _log(
        "AI_SELFIE_V265_REQUEST_CONTINUITY phase=start pid=%s host=%s source_photo=3 "
        "single_owner=true engine=dense68_engine_v265 legacy_fallback=false",
        request_pid,
        request_host,
    )

    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()
    stage1_b = bytes(stage1 or b"")
    source_b = bytes(source or b"")

    standard_pre, standard_pre_metrics, standard_desired = engine.transfer_attempt(
        stage1_b, source_b, yunet_path, dense_path, recognition_path, strict=False
    )
    standard_post, standard_post_metrics = engine.apply_ocular_lock(
        stage1_b,
        standard_pre,
        source_b,
        standard_desired,
        yunet_path,
        dense_path,
        recognition_path,
        standard_pre_metrics,
    )
    (
        standard,
        standard_metrics,
        standard_phase,
        standard_hard,
        standard_failures,
    ) = _select_ocular_candidate(
        "standard",
        standard_pre,
        standard_pre_metrics,
        standard_post,
        standard_post_metrics,
    )
    _quality_log(f"standard_{standard_phase}", standard_metrics, standard_hard, standard_failures)

    refinement = engine.visual_refinement_reasons(standard_metrics) if standard_hard else []
    if standard_hard and not refinement:
        _set_runtime_result(runtime, path=f"v265_standard_{standard_phase}", metrics=standard_metrics)
        pid, host = _process_identity()
        _log(
            "AI_SELFIE_V265_SELECT selected=standard_%s attempts=1 reason=hard_pass_no_refinement "
            "delivery_route=original_document_only person_b=pixel_locked no_neck=true "
            "independent_eye_patch=false pid_start=%s pid_end=%s host_start=%s host_end=%s",
            standard_phase,
            request_pid,
            pid,
            request_host,
            host,
        )
        return standard, f"opencv_dense68_roi_v265_standard_{standard_phase}"

    retry_reasons = refinement or standard_failures or ["quality_gate"]
    _log(
        "AI_SELFIE_V265_STRICT_RETRY status=triggered attempts=2 route=same_local_dense68 reason=%s "
        "provider_rescue=false legacy_fallback=false standard_candidate=%s",
        "|".join(retry_reasons),
        standard_phase,
    )

    strict_pre, strict_pre_metrics, strict_desired = engine.transfer_attempt(
        stage1_b, source_b, yunet_path, dense_path, recognition_path, strict=True
    )
    strict_post, strict_post_metrics = engine.apply_ocular_lock(
        stage1_b,
        strict_pre,
        source_b,
        strict_desired,
        yunet_path,
        dense_path,
        recognition_path,
        strict_pre_metrics,
    )
    (
        strict,
        strict_metrics,
        strict_phase,
        strict_hard,
        strict_failures,
    ) = _select_ocular_candidate(
        "strict",
        strict_pre,
        strict_pre_metrics,
        strict_post,
        strict_post_metrics,
    )
    _quality_log(f"strict_{strict_phase}", strict_metrics, strict_hard, strict_failures)

    decision = _final_candidate_decision(
        standard_hard,
        standard_metrics,
        strict_hard,
        strict_metrics,
    )
    pid, host = _process_identity()

    if decision == "strict":
        reason = (
            "standard_hard_fail_strict_pass"
            if not standard_hard
            else "strict_proven_better"
        )
        _set_runtime_result(runtime, path=f"v265_strict_{strict_phase}_selected", metrics=strict_metrics)
        _log(
            "AI_SELFIE_V265_SELECT selected=strict_%s attempts=2 reason=%s "
            "standard_candidate=%s standard_hard=%s strict_hard=%s "
            "standard_identity=%.6f strict_identity=%.6f standard_score=%.6f strict_score=%.6f "
            "delivery_route=original_document_only person_b=pixel_locked no_neck=true "
            "independent_eye_patch=false pid_start=%s pid_end=%s host_start=%s host_end=%s",
            strict_phase,
            reason,
            standard_phase,
            "PASS" if standard_hard else "FAIL",
            "PASS" if strict_hard else "FAIL",
            _metric(standard_metrics, "identity_similarity_cosine", 0.0),
            _metric(strict_metrics, "identity_similarity_cosine", 0.0),
            engine.visual_quality_score(standard_metrics),
            engine.visual_quality_score(strict_metrics),
            request_pid,
            pid,
            request_host,
            host,
        )
        return strict, f"opencv_dense68_roi_v265_strict_{strict_phase}_selected"

    if decision == "standard":
        reason = (
            "strict_hard_fail_standard_pass"
            if not strict_hard
            else "strict_not_proven_better"
        )
        _set_runtime_result(runtime, path=f"v265_standard_{standard_phase}_retained", metrics=standard_metrics)
        _log(
            "AI_SELFIE_V265_SELECT selected=standard_%s attempts=2 reason=%s "
            "strict_candidate=%s standard_hard=%s strict_hard=%s "
            "standard_identity=%.6f strict_identity=%.6f standard_score=%.6f strict_score=%.6f "
            "delivery_route=original_document_only person_b=pixel_locked no_neck=true "
            "independent_eye_patch=false pid_start=%s pid_end=%s host_start=%s host_end=%s",
            standard_phase,
            reason,
            strict_phase,
            "PASS" if standard_hard else "FAIL",
            "PASS" if strict_hard else "FAIL",
            _metric(standard_metrics, "identity_similarity_cosine", 0.0),
            _metric(strict_metrics, "identity_similarity_cosine", 0.0),
            engine.visual_quality_score(standard_metrics),
            engine.visual_quality_score(strict_metrics),
            request_pid,
            pid,
            request_host,
            host,
        )
        return standard, f"opencv_dense68_roi_v265_standard_{standard_phase}_retained"

    _log(
        "AI_SELFIE_V265_REJECT status=rejected attempts=2 provider_rescue=false legacy_fallback=false "
        "standard_candidate=%s strict_candidate=%s standard_failures=%s strict_failures=%s "
        "person_b=pixel_locked no_neck=true independent_eye_patch=false "
        "pid_start=%s pid_end=%s host_start=%s host_end=%s",
        standard_phase,
        strict_phase,
        "|".join(standard_failures) or "quality_gate",
        "|".join(strict_failures) or "quality_gate",
        request_pid,
        pid,
        request_host,
        host,
    )
    raise RuntimeError("V265 quality gate rejected PERSON-A after two local dense68 attempts")


async def _call_google(prompt: str, refs: list[tuple[str, bytes]], stage: str):
    """V265 stage-1 reference contract: crop only, but full head scaffold is authoritative."""
    patched = list(refs or [])
    if str(stage) == "composition_identity_separated":
        out: list[tuple[str, bytes]] = []
        count = 0
        for label, raw in patched:
            label_s = str(label or "")
            if label_s.startswith("USER SOURCE PHOTO"):
                count += 1
                out.append((
                    "USER VERIFIED HEAD/EXPRESSION CROP #3 — PERSON A ONLY. "
                    "AUTHORITATIVE for apparent age category, cranial silhouette, forehead/hairline, hair colour/style, "
                    "jaw/chin/cheek proportions and expression geometry. Inner identity texture is replaced by V265. "
                    "Do not infer phone, hand, arm, clothing or background from this crop.",
                    v241._expression_crop(bytes(raw)),
                ))
            else:
                out.append((label, raw))
        if count != 1:
            raise RuntimeError(f"V265 expected exactly one user source reference, got {count}")
        patched = out
        _log(
            "AI_SELFIE_V265_STAGE1_REF source=photo3 crop=head_expression age_lock=true head_shape_lock=true "
            "hair_lock=true full_source_reserved_for_dense68=true"
        )
    return await v241._google_request(prompt, patched, stage)


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    scene_rule = (
        "The first reference is the AUTHORITATIVE SCENE BASE. Preserve architecture, furniture, viewpoint, perspective and lighting. "
        if has_scene_image else f"Create this location faithfully: {scene}. "
    )
    is_selfie = "селфи" in str(shot_label).lower() or "selfie" in str(shot_label).lower()
    if is_selfie:
        shot_rule = (
            "TRUE FRONT-CAMERA SELFIE RESULT, NOT A THIRD-PERSON PHOTO OF SOMEONE TAKING A SELFIE. "
            "The viewer IS the phone front camera. NO phone, phone edge, case, screen, rear cameras, selfie stick, "
            "camera device, mirror-phone reflection, camera UI, foreground hand/arm or hand holding a device. "
            "Show only the resulting front-camera photograph. Exactly two people close to the lens at natural arm-length "
            "wide-angle perspective, heads/shoulders/upper torsos. PERSON A hands and forearms stay outside frame. "
        )
    else:
        shot_rule = "THIRD-PERSON JOINT PHOTO taken by another person. No visible phone, selfie stick, foreground device, camera UI or mirror-phone reflection. "

    return (
        "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
        f"{shot_rule}{scene_rule}"
        f"PERSON A is the USER on the LEFT. Source #{source_photo_no} is the authoritative PERSON-A head/expression scaffold. "
        "AGE/HEAD LOCK: preserve apparent age category exactly. Never adultize a child/teen, rejuvenate/age an adult, or beautify the craniofacial scaffold. "
        "Preserve head width/height ratio, skull/forehead silhouette, hairline, hair colour, hair length/style, ear placement, cheek volume, jaw width, chin length and head-to-shoulder proportion. "
        "EXPRESSION LOCK: preserve lip closure/opening, mouth width, smile amount/asymmetry, teeth visibility, jaw opening, cheek tension, eyelid opening/squint, eyebrow height and gaze. "
        "FACE SCAFFOLD LOCK: preserve normalized interocular distance, eye-line tilt, eye-to-nose distance, nose-to-mouth distance, mouth-corner spacing, nose width/length and lower-face/chin placement. "
        "Only inner facial identity texture is temporary; V265 physically replaces it. Keep PERSON A near-frontal, unobstructed, sharp, large and fully inside LEFT 48 percent. "
        f"PERSON B is {name} on the RIGHT. The HERO PORTRAIT references belong ONLY to PERSON B. Never mix identities between A and B. "
        "PERSON B stays entirely in RIGHT 48 percent. Natural anatomy, realistic skin and optics. No text, watermark, duplicate face, merged identity, morphing or hybrid face."
    )


def _document_name(raw: bytes) -> str:
    return "celebrity_selfie.png" if bytes(raw or b"").startswith(b"\x89PNG\r\n\x1a\n") else "celebrity_selfie.jpg"


async def _deliver_original_only(message: Any, raw: bytes, caption: str, *, prefer_document: bool) -> bytes:
    """Original-document delivery only. Retry transport; never downgrade image quality."""
    from telegram import InputFile

    data = bytes(raw or b"")
    if not prefer_document:
        raise RuntimeError("V265 refuses compressed/photo delivery for AI-selfie output")
    errors: list[str] = []
    for attempt, timeout in enumerate((300.0, 360.0, 420.0), 1):
        try:
            bio = io.BytesIO(data)
            bio.name = _document_name(data)
            await message.reply_document(
                document=InputFile(bio, filename=bio.name),
                caption=caption,
                write_timeout=timeout,
                read_timeout=timeout,
                connect_timeout=60.0,
                pool_timeout=60.0,
            )
            _log(
                "AI_SELFIE_V265_DELIVERY status=success attempt=%s original_document=true compressed_fallback=false bytes=%s",
                attempt, len(data),
            )
            return data
        except Exception as exc:
            errors.append(f"{type(exc).__name__}:{exc}")
            _log(
                "AI_SELFIE_V265_DELIVERY status=retry attempt=%s original_retained=true reason=%s:%s",
                attempt, type(exc).__name__, str(exc)[:220],
            )
            if attempt < 3:
                await asyncio.sleep(float(attempt * 3))
    raise RuntimeError("V265 original document delivery failed: " + " | ".join(errors))


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V246 UX base, then V265 as the only final selfie transfer owner."""
    if not callable(_BASE_V246_ENFORCE):
        raise RuntimeError("V265 base V246 enforcer was not captured")
    _BASE_V246_ENFORCE(bind_generate=bind_generate)

    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v211_delivery as delivery

    # Final algorithm owner.
    transfer._true_face_transfer = _true_face_transfer_v265
    delivery._deliver = _deliver_original_only

    # Final stage-1 scaffold owner. Patch V242 symbols too because V242 is a durable
    # reassertion boundary inside the older composition base.
    v242._call_google = _call_google
    v242._stage1_prompt = _stage1_prompt
    v241._call_google = _call_google
    v241._stage1_prompt = _stage1_prompt
    google._call_google = _call_google
    transfer._stage1_prompt = _stage1_prompt

    # Redirect only the two runtime reassertion entry points that may execute during
    # generation. V245 remains untouched so _BASE_V246_ENFORCE can safely call it.
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, delivery, v241, v242, v246):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v265-single-owner-dense68-roi-local-only-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini scene/PERSON-B + photo3 head/expression scaffold -> YuNet similarity -> "
            "PIPNet 68-point source-dominant ROI geometry -> source ocular lock -> "
            "MobileFace -> V265 production_gate -> optional same-engine strict attempt -> original PNG document"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V265_ENFORCE status=ok owner=v265 single_owner=true engine=dense68_engine_v265 landmarks=68 "
        "roi_only=true max_local_attempts=2 strict_same_engine=true provider_rescue=false v262_fallback=false "
        "legacy_runtime_fallback=false v263_quality_gate_in_execution=false eye_asymmetry_hard_gate=false "
        "person_b_protection=pixel_locked no_neck=true independent_eye_patch=false png=true "
        "delivery=original_document_only version=%s",
        VERSION,
    )


def _install_final_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_v265_single_owner_builder_lock"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return
    previous_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = previous_build(self, *args, **kwargs)
        enforce_runtime(bind_generate=True)
        setattr(app, "_neyrobot_v265_single_owner", True)
        _log("AI_SELFIE_V265_BIND status=ok final_builder=true extra_handlers=0")
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True


def install() -> None:
    global _INSTALLED, _BASE_V246_ENFORCE
    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return
    current = v246.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V246_ENFORCE = current
    _install_final_builder_hook()
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V265 single-owner dense68 runtime installed; legacy fallbacks disabled", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "production_gate",
    "_true_face_transfer_v265",
    "_stage1_prompt",
    "_call_google",
    "_deliver_original_only",
]
