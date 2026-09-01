# -*- coding: utf-8 -*-
"""V265 single production owner for AI-selfie generation.

There is exactly one PERSON-A identity-transfer algorithm in this runtime: the local
ROI-only 68-landmark engine in :mod:`dense68_engine_v265`.  Historical V247..V264
modules are not installed and are not recovery routes.

Contract:
- Gemini owns the scene and PERSON-B; the user crop owns PERSON-A age/head/hair and
  expression scaffold.
- photo #3 is the only PERSON-A identity source.
- YuNet + PIPNet-68 + MobileFace drive the local transfer and quality checks.
- one standard local candidate and at most one strict local candidate are allowed.
- no Segmind/PiAPI rescue, no V262 rollback, no alternate compositor, no compressed
  delivery fallback. Any infrastructure/algorithm failure fails closed.
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


def _thresholds(face_short: float) -> dict[str, float]:
    face = float(face_short or 0.0)
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
    """Hard delivery gate. Natural eye asymmetry is deliberately not a blocker."""
    face_short = float(metrics.get("target_face_short", 0.0) or 0.0)
    limits = _thresholds(face_short)
    identity = float(metrics.get("identity_similarity_cosine", 0.0) or 0.0)
    left_eye = float(metrics.get("left_eye_error", 1.0) or 1.0)
    right_eye = float(metrics.get("right_eye_error", 1.0) or 1.0)
    worst_eye = max(left_eye, right_eye)
    inner = float(metrics.get("inner_face_landmark_nme", 1.0) or 1.0)
    interocular = float(metrics.get("interocular_ratio_delta", 1.0) or 1.0)
    axis = float(metrics.get("nose_mouth_axis_delta", 1.0) or 1.0)
    asym = float(metrics.get("eye_asymmetry_delta", 0.0) or 0.0)

    if not all(math.isfinite(v) for v in (identity, worst_eye, inner, interocular, axis, asym)):
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
        float(metrics.get("identity_similarity_cosine", 0.0)),
        max(float(metrics.get("left_eye_error", 1.0)), float(metrics.get("right_eye_error", 1.0))),
        float(metrics.get("inner_face_landmark_nme", 1.0)),
        float(metrics.get("interocular_ratio_delta", 1.0)),
        float(metrics.get("nose_mouth_axis_delta", 1.0)),
        float(metrics.get("eye_asymmetry_delta", 0.0)),
        "none" if not failures else "|".join(failures),
    )


async def _true_face_transfer_v265(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    """Two local dense68 attempts maximum. There is no recovery algorithm."""
    if int(source_photo_no) != 3:
        raise RuntimeError(f"V265 requires authoritative photo #3, got #{source_photo_no}")

    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()
    stage1_b = bytes(stage1 or b"")
    source_b = bytes(source or b"")

    standard, standard_metrics, standard_desired = engine.transfer_attempt(
        stage1_b, source_b, yunet_path, dense_path, recognition_path, strict=False
    )
    standard, standard_metrics = engine.apply_ocular_lock(
        stage1_b,
        standard,
        source_b,
        standard_desired,
        yunet_path,
        dense_path,
        recognition_path,
        standard_metrics,
    )
    standard_legacy, standard_legacy_failures = v263._quality_gate(standard_metrics)
    standard_hard, standard_failures = production_gate(standard_metrics)
    _quality_log("standard", standard_metrics, bool(standard_legacy and standard_hard), standard_failures or standard_legacy_failures)

    refinement = engine.visual_refinement_reasons(standard_metrics) if standard_legacy and standard_hard else []
    if standard_legacy and standard_hard and not refinement:
        _set_runtime_result(runtime, path="v265_standard", metrics=standard_metrics)
        _log("AI_SELFIE_V265_SELECT selected=standard attempts=1 reason=hard_pass_no_refinement")
        return standard, "opencv_dense68_roi_v265_standard"

    retry_reasons = refinement or standard_failures or standard_legacy_failures or ["quality_gate"]
    _log(
        "AI_SELFIE_V265_STRICT_RETRY status=triggered attempts=2 route=same_local_dense68 reason=%s "
        "provider_rescue=false legacy_fallback=false",
        "|".join(retry_reasons),
    )

    strict, strict_metrics, strict_desired = engine.transfer_attempt(
        stage1_b, source_b, yunet_path, dense_path, recognition_path, strict=True
    )
    strict, strict_metrics = engine.apply_ocular_lock(
        stage1_b,
        strict,
        source_b,
        strict_desired,
        yunet_path,
        dense_path,
        recognition_path,
        strict_metrics,
    )
    strict_legacy, strict_legacy_failures = v263._quality_gate(strict_metrics)
    strict_hard, strict_failures = production_gate(strict_metrics)
    _quality_log("strict", strict_metrics, bool(strict_legacy and strict_hard), strict_failures or strict_legacy_failures)

    standard_ok = bool(standard_legacy and standard_hard)
    strict_ok = bool(strict_legacy and strict_hard)
    if standard_ok and strict_ok:
        prefer_strict = engine.prefer_strict_refinement(standard_metrics, strict_metrics)
        if prefer_strict:
            _set_runtime_result(runtime, path="v265_strict_selected", metrics=strict_metrics)
            _log(
                "AI_SELFIE_V265_SELECT selected=strict attempts=2 standard_identity=%.4f strict_identity=%.4f "
                "standard_score=%.5f strict_score=%.5f",
                float(standard_metrics.get("identity_similarity_cosine", 0.0)),
                float(strict_metrics.get("identity_similarity_cosine", 0.0)),
                engine.visual_quality_score(standard_metrics),
                engine.visual_quality_score(strict_metrics),
            )
            return strict, "opencv_dense68_roi_v265_strict_selected"
        _set_runtime_result(runtime, path="v265_standard_retained", metrics=standard_metrics)
        _log(
            "AI_SELFIE_V265_SELECT selected=standard attempts=2 reason=strict_not_better "
            "standard_identity=%.4f strict_identity=%.4f",
            float(standard_metrics.get("identity_similarity_cosine", 0.0)),
            float(strict_metrics.get("identity_similarity_cosine", 0.0)),
        )
        return standard, "opencv_dense68_roi_v265_standard_retained"

    if strict_ok:
        _set_runtime_result(runtime, path="v265_strict_recovery", metrics=strict_metrics)
        _log(
            "AI_SELFIE_V265_SELECT selected=strict attempts=2 reason=standard_hard_fail_strict_pass "
            "standard_failures=%s",
            "|".join(standard_failures or standard_legacy_failures) or "quality_gate",
        )
        return strict, "opencv_dense68_roi_v265_strict_recovery"

    if standard_ok:
        _set_runtime_result(runtime, path="v265_standard_retained", metrics=standard_metrics)
        _log(
            "AI_SELFIE_V265_SELECT selected=standard attempts=2 reason=strict_hard_fail_standard_pass "
            "strict_failures=%s",
            "|".join(strict_failures or strict_legacy_failures) or "quality_gate",
        )
        return standard, "opencv_dense68_roi_v265_standard_retained"

    _log(
        "AI_SELFIE_V265_REJECT status=rejected attempts=2 provider_rescue=false legacy_fallback=false "
        "standard_failures=%s strict_failures=%s",
        "|".join(standard_failures or standard_legacy_failures) or "quality_gate",
        "|".join(strict_failures or strict_legacy_failures) or "quality_gate",
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
            "MobileFace+dense hard gate -> optional same-engine strict attempt -> original PNG document"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V265_ENFORCE status=ok final_owner=v265 landmarks=68 roi_only=true "
        "max_local_attempts=2 provider_rescue=false v262_fallback=false legacy_fallback=false "
        "eye_asymmetry_hard_gate=false person_b=pixel_locked delivery=original_document_only version=%s",
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
