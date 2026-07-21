# -*- coding: utf-8 -*-
"""Celebrity Selfie v151: Comet-only composition-ready scene plates.

Production v150 proved that the configured CometAPI image endpoint is reachable,
but it still fell through to stale Gemini credentials whenever the strict
"completely empty background" vision gate rejected an otherwise usable scene.
That turned a recoverable composition issue into a hard provider failure.

v151 removes Gemini/FLUX from this feature's scene path and keeps identity work
fully local: Comet creates only a composition-ready location plate, while the
user and selected public figure are inserted from verified source-pixel cutouts.
The background gate rejects only unusable exposure/resolution and prominent
foreground faces; small, defocused background people are allowed so restaurant,
premiere and public-place scenes can remain natural. Three prompt variants are
tried before the request fails without charging.
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144
import celebrity_selfie_v147 as v147
import celebrity_selfie_v149 as v149
import celebrity_selfie_v150 as v150

VERSION = "v151-comet-only-composition-ready-2026-07-21"
_GROUP = -2_100_001_400
_BUILDER_FLAG = "_celebrity_selfie_v151_builder"
_HANDLER_FLAG = "_celebrity_selfie_v151_handlers"
_LAST_RUN_DEBUG: dict[str, Any] = {}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _safe_error(exc: BaseException) -> str:
    return v139._safe_error(exc)


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _scene_provider_order() -> list[str]:
    """The celebrity-selfie scene path is intentionally Comet-only."""
    return ["comet"]


def _comet_model() -> str:
    return str(
        os.environ.get("CELEBRITY_V151_COMET_IMAGE_MODEL")
        or os.environ.get("CELEBRITY_V150_COMET_IMAGE_MODEL")
        or os.environ.get("COMET_IMAGE_GEN_MODEL")
        or "gpt-image-1"
    ).strip()


def _scene_prompt(scene: str, aspect: str, variant: int) -> str:
    safe_aspect = v144._normalise_aspect(aspect)
    profiles = (
        "premium smartphone photograph, natural practical light, realistic depth of field",
        "editorial mobile photo, coherent perspective, subtle cinematic lighting",
        "high-end candid phone photograph, realistic materials and restrained HDR",
        "natural event photograph, believable lens perspective and soft background depth",
    )
    layout_notes = (
        "keep both foreground zones open and balanced",
        "leave slightly more open space on the left while preserving a clear right zone",
        "leave slightly more open space on the right while preserving a clear left zone",
        "use a wider composition with generous headroom in both foreground zones",
    )
    return (
        "Create ONE seamless photorealistic location plate for a later two-person selfie composite. "
        "Do not create either of the two main subjects. Reserve two natural adult placement zones in the "
        "foreground: one around x=30% on the LEFT and one around x=70% on the RIGHT, with unobstructed head, "
        "shoulder and torso space, believable floor/table/railing contact, and matching perspective. "
        "There must be no close or medium foreground person, no prominent face, no portrait, no mannequin, "
        "no human-shaped placeholder and no cropped body in either placement zone. Small distant background "
        "guests are allowed only when defocused, secondary and not visually dominant. Do not place a large object "
        "across either reserved zone. The image must look like a real photograph before people are inserted. "
        f"Requested setting: {v144._scene_profile(scene)}. Composition instruction: {layout_notes[variant % len(layout_notes)]}. "
        f"Style: {profiles[variant % len(profiles)]}. Use aspect ratio {safe_aspect}. "
        "No collage, split screen, border, caption, text, logo or watermark. Return only the final location plate."
    )


def _prominent_face_problem(raw: bytes) -> tuple[str, list[dict[str, float]]]:
    image = _open_rgb(raw)
    prominent: list[dict[str, float]] = []
    maximum_ratio = _number("CELEBRITY_V151_MAX_BACKGROUND_FACE_RATIO", 0.018, 0.004, 0.08)
    lower_zone_ratio = _number("CELEBRITY_V151_LOWER_ZONE_FACE_RATIO", 0.010, 0.003, 0.05)
    for face in v143._main_faces(raw):
        width = max(0.0, float(face.get("w") or 0))
        height = max(0.0, float(face.get("h") or 0))
        ratio = (width * height) / max(1.0, float(image.width * image.height))
        cx = (float(face.get("x") or 0) + width / 2.0) / max(1.0, image.width)
        cy = (float(face.get("y") or 0) + height / 2.0) / max(1.0, image.height)
        row = {"area_ratio": round(ratio, 5), "center_x": round(cx, 4), "center_y": round(cy, 4)}
        if ratio >= maximum_ratio or (cy >= 0.28 and ratio >= lower_zone_ratio):
            prominent.append(row)
    if prominent:
        return f"scene contains {len(prominent)} prominent foreground face(s)", prominent
    return "", prominent


def _composition_ready_problem(raw: bytes) -> tuple[str, dict[str, Any]]:
    try:
        metrics = dict(v139._image_metrics(raw))
        minimum_side = _number("CELEBRITY_V151_MIN_BACKGROUND_SIDE", 640, 320, 1600)
        if float(metrics.get("short_side") or 0) < minimum_side:
            return "scene resolution is too small", {"metrics": metrics}
        brightness = float(metrics.get("brightness") or 0)
        contrast = float(metrics.get("contrast") or 0)
        if brightness < 12 or brightness > 250 or contrast < 3.5:
            return "scene exposure or contrast is unusable", {"metrics": metrics}
        face_problem, prominent = _prominent_face_problem(raw)
        details = {"metrics": metrics, "prominent_faces": prominent}
        if face_problem:
            return face_problem, details
        return "", details
    except Exception as exc:
        return f"invalid scene plate: {_safe_error(exc)}", {}


async def _advisory_scene_qc(mod: Any, raw: bytes, scene: str) -> dict[str, Any]:
    """Use existing vision QC as telemetry, never as a provider failover trigger."""
    try:
        result = await v147._background_vision_qc(mod, raw, scene)
        return dict(result or {})
    except Exception as exc:
        return {"accepted": True, "unknown": True, "reason": f"advisory-qc-unavailable:{_safe_error(exc)}"[:400]}


async def _make_background_candidates(
    mod: Any,
    scene: str,
    aspect: str,
    user_photo: bytes,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    del user_photo
    safe_aspect = v144._normalise_aspect(aspect)
    debug["scene_aspect_requested"] = str(aspect or "-")
    debug["scene_aspect_normalized"] = safe_aspect
    debug["scene_generation_contract"] = "comet-only+composition-ready-local-gate+advisory-vision"
    debug["scene_provider_order"] = _scene_provider_order()
    debug["comet_model"] = _comet_model()
    debug.setdefault("background_attempts", [])
    debug.setdefault("scene_candidates", [])

    if not v150._comet_key():
        debug["background_attempts"].append({
            "stage": "v151_comet_key", "provider": "comet", "status": "error", "error": "COMET_API_KEY missing",
        })
        return []

    attempts = _integer("CELEBRITY_V151_COMET_BACKGROUNDS", 3, 2, 5)
    candidates: list[dict[str, Any]] = []
    for index in range(attempts):
        label = f"v151_background_comet_{index + 1}"
        prompt = _scene_prompt(scene, safe_aspect, index)
        stage = v139._stage_start(debug, label, f"comet:{_comet_model()}", aspect=safe_aspect, people="background-only")
        attempt: dict[str, Any] = {
            "stage": label,
            "provider": f"comet:{_comet_model()}",
            "aspect": safe_aspect,
            "prompt_variant": index + 1,
        }
        debug["background_attempts"].append(attempt)
        try:
            raw = await v150._comet_scene(prompt, safe_aspect, debug)
            problem, local_qc = _composition_ready_problem(raw)
            attempt["local_qc"] = local_qc
            if problem:
                raise v139.PipelineError("scene_composition_qc", problem)

            advisory = await _advisory_scene_qc(mod, raw, scene)
            metrics = dict(local_qc.get("metrics") or {})
            vision_quality = float(advisory.get("quality") or 0)
            if advisory.get("unknown"):
                vision_quality = 60.0
            score = (
                min(100.0, float(metrics.get("short_side") or 0) / 11.0) * 0.30
                + min(100.0, float(metrics.get("contrast") or 0) * 2.2) * 0.25
                + max(35.0, vision_quality) * 0.25
                + 20.0
            )
            row = {
                "label": label,
                "provider": f"comet:{_comet_model()}",
                "score": round(min(100.0, score), 2),
                "output": raw,
                "aspect": safe_aspect,
                "people": "background-small-allowed",
                "local_composition_qc": local_qc,
                "vision_background_qc": advisory,
                "vision_qc_mode": "advisory-only",
            }
            candidates.append(row)
            debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
            attempt.update(status="ok", score=row["score"], advisory_accepted=advisory.get("accepted"))
            v139._stage_finish(stage, "ok", score=row["score"], bytes=len(raw), advisory=advisory)
        except Exception as exc:
            message = _safe_error(exc)
            attempt.update(status="error", error=message[:900])
            v139._record_error(debug, stage, exc)

    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


async def _run_v151_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    global _LAST_RUN_DEBUG
    started = time.time()
    contract = {
        "version": VERSION,
        "architecture": "comet-scene-plate+verified-source-pixel-dual-composite",
        "scene_provider_order": _scene_provider_order(),
        "gemini_scene": "disabled",
        "flux_scene": "disabled",
        "local_placeholder_background": "disabled",
        "scene_qc": "local-composition-ready+advisory-vision",
        "user_face_generation": "disabled",
        "celebrity_face_generation": "disabled",
        "face_swap": "disabled",
        "credit_charge_on_failure": False,
    }
    try:
        output, debug = await v149._run_v149_generation(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            previous_result=previous_result,
            additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update(contract)
        debug["v151_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update(contract)
        debug["v151_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        if isinstance(exc, v139.PipelineError):
            exc.debug = debug
        raise


async def _run_compat(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> bytes:
    output, _ = await _run_v151_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def _patch_version_contract() -> None:
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning

        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION
    except Exception:
        pass


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or session.get("v139_debug") or _LAST_RUN_DEBUG or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=comet_scene_plate+verified_source_pixel_dual_composite",
        "scene_provider_order=comet",
        f"comet={'ready' if bool(v150._comet_key()) else 'missing'}",
        f"comet_model={_comet_model()}",
        "gemini_scene=disabled",
        "flux_scene=disabled",
        "local_placeholder_background=disabled",
        "scene_qc=local_composition_ready+advisory_vision",
        "user_face_generation=disabled",
        "celebrity_face_generation=disabled",
        "face_swap=disabled",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"background_attempts={str(debug.get('background_attempts') or '-')[:1800]}",
        f"selected={str(debug.get('selected') or '-')[:800]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v150.install()

    os.environ["CELEBRITY_V150_SCENE_PROVIDERS"] = "comet"
    os.environ["CELEBRITY_V147_SCENE_PROVIDERS"] = "comet"
    os.environ["CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK"] = "0"
    os.environ.setdefault("CELEBRITY_V151_COMET_BACKGROUNDS", "3")
    os.environ.setdefault("CELEBRITY_V151_MAX_BACKGROUND_FACE_RATIO", "0.018")
    os.environ.setdefault("CELEBRITY_V151_LOWER_ZONE_FACE_RATIO", "0.010")
    os.environ.setdefault("CELEBRITY_V151_MIN_BACKGROUND_SIDE", "640")

    v142._make_plate_candidates = _make_background_candidates
    v147._make_background_candidates = _make_background_candidates
    v150._make_background_candidates = _make_background_candidates

    v139.selfie._run_v151_generation = _run_v151_generation
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._diag = _diag
    _patch_version_contract()


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        install()
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v151", "diag_selfie_v150", "diag_selfie_v149",
                "diag_selfie_v148", "diag_selfie_v147", "diag_selfie_v146",
                "diag_selfie_v145", "diag_selfie_v144", "diag_selfie_v143",
                "diag_celebrity_flow", "diag_brand",
            ):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_early() -> None:
    install()
    install_builder_hook()


__all__ = [
    "VERSION",
    "install",
    "install_early",
    "install_builder_hook",
    "_scene_provider_order",
    "_comet_model",
    "_scene_prompt",
    "_prominent_face_problem",
    "_composition_ready_problem",
    "_make_background_candidates",
    "_run_v151_generation",
    "_diag",
]
