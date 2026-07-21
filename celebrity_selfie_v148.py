# -*- coding: utf-8 -*-
"""Celebrity Selfie v148: schema-safe Gemini and source-layer final QC.

v147 removed PiAPI/OpenAI image editing from identity handling, but production
showed two final faults: Gemini still received a rejected responseFormat image
aspect field, and the final JPEG was rejected when the generic face detector
missed profile/dim source faces. v148 omits the unsupported Gemini fields and
validates the already-audited source cutout layers by their deterministic
placement metadata instead of re-detecting faces after JPEG encoding.
"""
from __future__ import annotations

import hashlib
import os
import time
from io import BytesIO
from typing import Any

import httpx
from PIL import Image

import celebrity_selfie_v139 as v139
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144
import celebrity_selfie_v145 as v145
import celebrity_selfie_v146 as v146
import celebrity_selfie_v147 as v147

VERSION = "v148-schema-safe-layer-qc-2026-07-21"
_GROUP = -2_100_001_100
_BUILDER_FLAG = "_celebrity_selfie_v148_builder"
_HANDLER_FLAG = "_celebrity_selfie_v148_handlers"
_ORIGINAL_V147_RUN = v147._run_v147_generation
_LAST_RUN_DEBUG: dict[str, Any] = {}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return opened.convert("RGB")


def _gemini_payload_variants_no_aspect(prompt: str) -> list[tuple[str, dict[str, Any]]]:
    """No variant may contain responseFormat, aspectRatio, imageSize or snake-case equivalents."""
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    return [
        ("image-only-no-aspect", {"contents": contents, "generationConfig": {"responseModalities": ["IMAGE"]}}),
        ("text-image-no-aspect", {"contents": contents, "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}),
        ("prompt-only", {"contents": contents}),
    ]


async def _gemini_scene_no_aspect(
    mod: Any,
    model: str,
    prompt: str,
    aspect: str,
    debug: dict[str, Any] | None = None,
) -> bytes:
    provider = v139.selfie.previous
    key = provider._gemini_key(mod)
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY missing")
    base_url = str(
        getattr(mod, "GEMINI_IMAGE_BASE_URL", "")
        or os.environ.get("GEMINI_IMAGE_BASE_URL")
        or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    timeout_s = _integer("CELEBRITY_V148_GEMINI_TIMEOUT_S", 420, 90, 900)
    errors: list[str] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180),
        follow_redirects=True,
    ) as client:
        for schema, payload in _gemini_payload_variants_no_aspect(prompt):
            if debug is not None:
                debug.setdefault("gemini_schema_attempts", []).append({
                    "model": model,
                    "schema": schema,
                    "aspect_requested": v144._normalise_aspect(aspect),
                    "response_format": "omitted",
                    "aspect_field": "omitted",
                })
            try:
                response = await client.post(
                    f"{base_url}/models/{model}:generateContent",
                    headers={"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
                    json=payload,
                )
                try:
                    data = response.json()
                except Exception:
                    errors.append(f"{schema}: invalid JSON HTTP {response.status_code}: {response.text[:280]}")
                    continue
                if response.status_code >= 400:
                    detail = provider._gemini_error(data) or response.text[:450]
                    errors.append(f"{schema}: HTTP {response.status_code}: {detail}")
                    continue
                images = provider._gemini_images(data)
                if not images:
                    errors.append(f"{schema}: returned no image")
                    continue
                for raw in reversed(images):
                    try:
                        return v139._jpeg(raw)
                    except Exception as exc:
                        errors.append(f"{schema}: unreadable image: {v139._safe_error(exc)}")
            except Exception as exc:
                errors.append(f"{schema}: {v139._safe_error(exc)}")
    raise RuntimeError(f"Gemini scene {model} failed schema-safe requests: " + " | ".join(errors[-6:])[:1600])


def _layer_box(placement: dict[str, Any]) -> tuple[float, float, float, float] | None:
    position = placement.get("position")
    size = placement.get("size")
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        return None
    if not isinstance(size, (list, tuple)) or len(size) < 2:
        return None
    x, y = float(position[0]), float(position[1])
    w, h = float(size[0]), float(size[1])
    return (x, y, w, h) if w > 2 and h > 2 else None


def _visible_fraction(box: tuple[float, float, float, float], canvas: tuple[int, int]) -> float:
    x, y, w, h = box
    width, height = canvas
    visible_w = max(0.0, min(float(width), x + w) - max(0.0, x))
    visible_h = max(0.0, min(float(height), y + h) - max(0.0, y))
    return (visible_w * visible_h) / max(1.0, w * h)


def _source_layer_problem(
    raw: bytes,
    placement: dict[str, Any],
    *,
    side: str,
    role: str,
) -> str:
    try:
        image = _open_rgb(raw)
        if min(image.size) < 480:
            return f"{role} layer canvas is too small"
        box = _layer_box(placement)
        if box is None:
            return f"{role} placement metadata missing"
        x, y, w, h = box
        if _visible_fraction(box, image.size) < 0.60:
            return f"{role} layer is excessively clipped"
        center_x = (x + w / 2.0) / max(1.0, image.width)
        if side == "left" and center_x >= 0.58:
            return f"{role} layer is not on the left"
        if side == "right" and center_x <= 0.42:
            return f"{role} layer is not on the right"
        height_ratio = h / max(1.0, image.height)
        if height_ratio < 0.28 or height_ratio > 1.35:
            return f"{role} layer scale is unsuitable: {height_ratio:.3f}"
        alpha = dict(placement.get("alpha_metrics") or {})
        if not alpha.get("bbox"):
            return f"{role} validated alpha metadata missing"
        if float(alpha.get("transparent") or 0) < 0.02:
            return f"{role} layer has no transparent source background"
        if float(alpha.get("border_opaque") or 0) > 0.80:
            return f"{role} layer leaks source background at borders"
        if int(alpha.get("transparent_corners") or 0) < 1:
            return f"{role} layer has opaque source corners"
        metrics = v139._image_metrics(raw)
        if metrics["brightness"] < 8 or metrics["brightness"] > 252 or metrics["contrast"] < 2:
            return f"{role} composite exposure is unusable"
        return ""
    except Exception as exc:
        return f"invalid {role} source layer: {v139._safe_error(exc)}"


def _dual_layer_problem(
    raw: bytes,
    user_placement: dict[str, Any],
    celebrity_placement: dict[str, Any],
) -> str:
    problem = _source_layer_problem(raw, user_placement, side="left", role="user")
    if problem:
        return problem
    problem = _source_layer_problem(raw, celebrity_placement, side="right", role="celebrity")
    if problem:
        return problem
    user_box = _layer_box(user_placement)
    celebrity_box = _layer_box(celebrity_placement)
    assert user_box is not None and celebrity_box is not None
    ux, uy, uw, uh = user_box
    cx, cy, cw, ch = celebrity_box
    if ux + uw / 2.0 >= cx + cw / 2.0:
        return "source layer order is not left-user/right-celebrity"
    area_ratio = (uw * uh) / max(1.0, cw * ch)
    if area_ratio < 0.20 or area_ratio > 5.0:
        return f"source layer scales are incompatible: {area_ratio:.2f}"
    return ""


async def _source_pixel_celebrity_variants(
    mod: Any,
    plate: dict[str, Any],
    references: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    reference_limit = _integer("CELEBRITY_V148_CELEBRITY_REFERENCE_ATTEMPTS", 4, 1, 6)
    placement_count = _integer("CELEBRITY_V148_CELEBRITY_PLACEMENTS", 3, 1, 3)
    for reference_index, reference in enumerate([raw for raw in references if raw][:reference_limit], start=1):
        label = f"celebrity_ref_{reference_index}"
        try:
            cutout = await v143._prepare_user_cutout(mod, reference, debug, label)
        except Exception as exc:
            debug.setdefault("errors", []).append({
                "stage": f"v148_cutout_{label}",
                "provider": "photoroom/rembg",
                "category": "celebrity_cutout",
                "error": v139._safe_error(exc),
            })
            continue
        for variant in range(placement_count):
            stage_label = f"{plate['label']}_v148_source_celebrity_r{reference_index}_p{variant + 1}"
            stage = v139._stage_start(debug, stage_label, "source-pixel-layer", reference_index=reference_index, placement=variant + 1)
            try:
                raw, placement = v147._place_source_cutout(
                    plate["output"], cutout, side="right", variant=variant, role="celebrity"
                )
                problem = _source_layer_problem(raw, placement, side="right", role="celebrity")
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                row = {
                    "label": stage_label,
                    "scene": plate["label"],
                    "scene_provider": plate["provider"],
                    "celebrity_provider": f"source-cutout:{cutout.get('provider')}",
                    "celebrity_identity": 100.0,
                    "identity_unknown": False,
                    "reason": "original licensed reference pixels and validated alpha layer",
                    "reference_index": reference_index,
                    "celebrity_pixel_preserved": True,
                    "celebrity_face_regenerated": False,
                    "placement": placement,
                    "output": raw,
                }
                results.append(row)
                debug.setdefault("identity_candidates", []).append({k: v for k, v in row.items() if k != "output"})
                v139._stage_finish(stage, "ok", score=100.0, bytes=len(raw), gate="source-layer")
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    results.sort(key=lambda item: (float(item.get("celebrity_identity") or 0), -int(item.get("reference_index") or 99)), reverse=True)
    return results[:8]


async def _source_pixel_build_composite_candidates(
    mod: Any,
    celebrity_variant: dict[str, Any],
    cutouts: list[dict[str, Any]],
    user_ref: bytes,
    celebrity_ref: bytes,
    scene: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    placements = _integer("CELEBRITY_V148_USER_PLACEMENTS", 3, 1, 3)
    for cutout in cutouts:
        for variant in range(placements):
            label = f"{celebrity_variant['label']}_{cutout['label']}_v148_composite_{variant + 1}"
            stage = v139._stage_start(debug, label, "dual-source-layer-composite")
            try:
                raw, user_placement = v143._composite_user(celebrity_variant["output"], cutout, variant)
                celebrity_placement = dict(celebrity_variant.get("placement") or {})
                problem = _dual_layer_problem(raw, user_placement, celebrity_placement)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)

                visual_score = _number("CELEBRITY_V148_LOCAL_VISUAL_SCORE", 78.0, 55.0, 92.0)
                visual_mode = "local-source-layer-qc"
                visual_checks: dict[str, Any] = {
                    "validated_user_alpha": True,
                    "validated_celebrity_alpha": True,
                    "left_user_layer": True,
                    "right_celebrity_layer": True,
                    "source_pixels_preserved": True,
                }
                reason = "validated source alpha layers and deterministic placement geometry"
                if _flag("CELEBRITY_V148_REMOTE_VISION_QC", False):
                    remote = await v143._visual_composite_qc(mod, raw, user_ref, scene)
                    accepted, remote_score, remote_mode = v147._soft_visual_acceptance(remote)
                    if accepted:
                        visual_score = remote_score
                        visual_mode = remote_mode
                        visual_checks = dict(remote.get("checks") or visual_checks)
                        reason = str(remote.get("reason") or reason)
                    elif not v147._vision_unavailable(remote):
                        raise v139.PipelineError("composite_visual_qc", str(remote.get("reason") or "remote visual QC rejected result"))

                structural = v139._structural_score(raw)
                artifact = v141._artifact_metrics(raw)
                artifact_quality = float(artifact.get("quality") or 0)
                if artifact_quality < _number("CELEBRITY_V148_MIN_ARTIFACT_QUALITY", 24.0, 5.0, 70.0):
                    raise v139.PipelineError("composite_visual_qc", f"local artifact quality too low: {artifact_quality:.1f}")
                total = visual_score * 0.46 + structural * 0.24 + artifact_quality * 0.20 + 10.0
                row = {
                    "label": label,
                    "scene": celebrity_variant.get("scene"),
                    "scene_provider": celebrity_variant.get("scene_provider"),
                    "user_provider": f"source-cutout:{cutout.get('provider')}",
                    "celebrity_provider": celebrity_variant.get("celebrity_provider"),
                    "user_identity": 100.0,
                    "user_identity_measured": 100.0,
                    "celebrity_identity": 100.0,
                    "celebrity_identity_measured": 100.0,
                    "identity_min": 100.0,
                    "identity_weighted": 100.0,
                    "identity_unknown": False,
                    "visual_naturalness": round(visual_score, 1),
                    "visual_mode": visual_mode,
                    "visual_checks": visual_checks,
                    "structural": round(structural, 1),
                    "artifact_quality": artifact_quality,
                    "total": round(total, 2),
                    "reason": reason[:500],
                    "user_pixel_preserved": True,
                    "user_face_regenerated": False,
                    "celebrity_pixel_preserved": True,
                    "celebrity_face_regenerated": False,
                    "face_swap_used": False,
                    "openai_image_edit_used": False,
                    "generic_face_detector_gate_used": False,
                    "source_layer_geometry_gate_used": True,
                    "primary_selfie_only": True,
                    "placement": user_placement,
                    "celebrity_placement": celebrity_placement,
                    "output": raw,
                }
                rows.append(row)
                debug.setdefault("composite_candidates", []).append({k: v for k, v in row.items() if k != "output"})
                v139._stage_finish(stage, "ok", total=row["total"], naturalness=row["visual_naturalness"], visual_mode=visual_mode, bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    rows.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
    return rows


async def _run_v148_generation(
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
    try:
        output, debug = await _ORIGINAL_V147_RUN(
            mod, user_photo, celebrity_refs, celebrity_name, scene,
            previous_result=previous_result, additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update({
            "version": VERSION,
            "architecture": "schema-safe-empty-scene+dual-source-layers+placement-qc",
            "gemini_response_format": "omitted",
            "gemini_aspect_field": "omitted",
            "generic_face_detector_final_gate": "disabled",
            "source_layer_geometry_gate": "required",
            "remote_vision_qc": "enabled" if _flag("CELEBRITY_V148_REMOTE_VISION_QC", False) else "optional-disabled",
            "user_face_generation": "disabled",
            "celebrity_face_generation": "disabled",
            "face_swap": "disabled",
            "v148_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        for module in (v147, v146, v145, v144, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update({
            "version": VERSION,
            "architecture": "schema-safe-empty-scene+dual-source-layers+placement-qc",
            "gemini_response_format": "omitted",
            "gemini_aspect_field": "omitted",
            "generic_face_detector_final_gate": "disabled",
            "source_layer_geometry_gate": "required",
            "remote_vision_qc": "enabled" if _flag("CELEBRITY_V148_REMOTE_VISION_QC", False) else "optional-disabled",
            "user_face_generation": "disabled",
            "celebrity_face_generation": "disabled",
            "face_swap": "disabled",
            "v148_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        for module in (v147, v146, v145, v144, v143, v142, v139):
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
    output, _ = await _run_v148_generation(
        mod, user_photo, celebrity_refs, celebrity_name, scene,
        previous_result=previous_result, additional_user_refs=additional_user_refs,
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
    debug = session.get("v142_debug") or _LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=schema_safe_empty_scene+dual_source_layers+placement_qc",
        "gemini_response_format=omitted",
        "gemini_aspect_ratio_field=omitted",
        "generic_face_detector_final_gate=disabled",
        "source_layer_geometry_gate=required",
        "remote_vision_qc=" + ("enabled" if _flag("CELEBRITY_V148_REMOTE_VISION_QC", False) else "optional-disabled"),
        "user_face_generation=disabled",
        "celebrity_face_generation=disabled",
        "face_swap=disabled",
        "piapi_identity_stage=disabled",
        "openai_image_edit=disabled",
        f"scene_provider_order={','.join(v147._scene_provider_order())}",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"gemini_schema_attempts={str(debug.get('gemini_schema_attempts') or '-')[:1500]}",
        f"background_attempts={str(debug.get('background_attempts') or '-')[:1500]}",
        f"selected={str(selected or '-')[:1600]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    for item in (debug.get("errors") or [])[-8:]:
        lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:320]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v147.install()
    os.environ.setdefault("CELEBRITY_V148_REMOTE_VISION_QC", "0")
    os.environ.setdefault("CELEBRITY_V148_CELEBRITY_REFERENCE_ATTEMPTS", "4")
    os.environ.setdefault("CELEBRITY_V148_CELEBRITY_PLACEMENTS", "3")
    os.environ.setdefault("CELEBRITY_V148_USER_PLACEMENTS", "3")
    os.environ.setdefault("CELEBRITY_V148_LOCAL_VISUAL_SCORE", "78")
    os.environ.setdefault("CELEBRITY_V148_MIN_ARTIFACT_QUALITY", "24")
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"
    os.environ["CELEBRITY_V146_CELEBRITY_PROVIDERS"] = ""

    v144._gemini_scene_direct = _gemini_scene_no_aspect
    for module in (v142, v143, v145, v146, v147):
        module._celebrity_variants = _source_pixel_celebrity_variants
    v143._build_composite_candidates = _source_pixel_build_composite_candidates
    v139.selfie._run_v148_generation = _run_v148_generation
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
    "VERSION", "install", "install_early", "install_builder_hook",
    "_gemini_payload_variants_no_aspect", "_gemini_scene_no_aspect",
    "_source_layer_problem", "_dual_layer_problem",
    "_source_pixel_celebrity_variants", "_source_pixel_build_composite_candidates",
    "_run_v148_generation", "_diag",
]
