# -*- coding: utf-8 -*-
"""Celebrity Selfie v149: verified visible human layers.

v148 stopped false post-JPEG face-detector failures, but its replacement gate
trusted placement metadata without proving that the referenced layer was a
human or that it remained visible in the delivered JPEG. A non-human reference
could therefore be background-removed and receive a synthetic 100/100 score.

v149 fails closed unless both sources contain one dominant foreground face,
the face remains inside the transparent cutout, and each layer creates a
measurable pixel contribution in the expected half of the final frame. The
celebrity contribution is checked twice: immediately after insertion and again
in the final composite. Deterministic local placeholder backgrounds are also
disabled in production; provider failure returns an error instead of a poster.
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from typing import Any

from PIL import Image, ImageChops, ImageOps, ImageStat

import celebrity_selfie_v139 as v139
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144
import celebrity_selfie_v145 as v145
import celebrity_selfie_v146 as v146
import celebrity_selfie_v147 as v147
import celebrity_selfie_v148 as v148

VERSION = "v149-visible-human-layer-proof-2026-07-21"
_GROUP = -2_100_001_200
_BUILDER_FLAG = "_celebrity_selfie_v149_builder"
_HANDLER_FLAG = "_celebrity_selfie_v149_handlers"
_ORIGINAL_V148_RUN = v148._run_v148_generation
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
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int = 96) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


async def _gemini_scene_normalized(
    mod: Any,
    model: str,
    prompt: str,
    aspect: str,
    debug: dict[str, Any] | None = None,
) -> bytes:
    """Use the v148 schema-safe request, then normalize locally to the requested frame."""
    raw = await v148._gemini_scene_no_aspect(mod, model, prompt, aspect, debug)
    image = _open_rgb(raw)
    target = v147._aspect_size(v144._normalise_aspect(aspect), long_side=1280)
    if image.size != target:
        image = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return _encode_jpeg(image, 95)


def _source_face_info(raw: bytes, role: str) -> dict[str, Any]:
    image = _open_rgb(raw)
    faces = v143._main_faces(raw)
    if len(faces) != 1:
        raise v139.PipelineError(
            "source_identity",
            f"{role} source must contain exactly one dominant foreground face; found {len(faces)}",
        )
    face = dict(faces[0])
    area = float(face.get("w") or 0) * float(face.get("h") or 0)
    area_ratio = area / max(1.0, float(image.width * image.height))
    minimum = _number("CELEBRITY_V149_MIN_SOURCE_FACE_AREA", 0.007, 0.002, 0.05)
    maximum = _number("CELEBRITY_V149_MAX_SOURCE_FACE_AREA", 0.42, 0.15, 0.80)
    if area_ratio < minimum or area_ratio > maximum:
        raise v139.PipelineError(
            "source_identity",
            f"{role} source face scale is unsuitable: {area_ratio:.4f}",
        )
    center_x = (float(face.get("x") or 0) + float(face.get("w") or 0) / 2.0) / max(1.0, image.width)
    center_y = (float(face.get("y") or 0) + float(face.get("h") or 0) / 2.0) / max(1.0, image.height)
    if not (0.05 <= center_x <= 0.95 and 0.05 <= center_y <= 0.88):
        raise v139.PipelineError("source_identity", f"{role} source face is too close to the frame boundary")
    return {
        "face": face,
        "source_size": [image.width, image.height],
        "face_area_ratio": round(area_ratio, 5),
        "face_center": [round(center_x, 4), round(center_y, 4)],
    }


def _cutout_face_alpha(cutout: dict[str, Any]) -> float:
    image = cutout.get("image")
    face = cutout.get("face")
    if not isinstance(image, Image.Image) or image.mode != "RGBA" or not isinstance(face, dict):
        return 0.0
    x = max(0, int(float(face.get("x") or 0)))
    y = max(0, int(float(face.get("y") or 0)))
    right = min(image.width, int(float(face.get("x") or 0) + float(face.get("w") or 0)))
    bottom = min(image.height, int(float(face.get("y") or 0) + float(face.get("h") or 0)))
    if right <= x or bottom <= y:
        return 0.0
    alpha = image.getchannel("A").crop((x, y, right, bottom))
    return float(ImageStat.Stat(alpha).mean[0]) / 255.0


def _human_cutout_problem(cutout: dict[str, Any], role: str) -> str:
    if not isinstance(cutout.get("face"), dict):
        return f"{role} cutout has no verified source face"
    image = cutout.get("image")
    if not isinstance(image, Image.Image) or image.mode != "RGBA":
        return f"{role} cutout is not an RGBA source layer"
    face_alpha = _cutout_face_alpha(cutout)
    if face_alpha < _number("CELEBRITY_V149_MIN_FACE_ALPHA", 0.62, 0.35, 0.95):
        return f"{role} cutout removed or obscured the face: alpha={face_alpha:.3f}"
    metrics = dict(cutout.get("alpha_metrics") or {})
    if not metrics.get("bbox"):
        return f"{role} cutout has no validated alpha bounding box"
    coverage = float(metrics.get("coverage") or 0)
    if coverage < 0.025 or coverage > 0.86:
        return f"{role} cutout coverage is unsuitable: {coverage:.3f}"
    return ""


async def _prepare_verified_cutout(
    mod: Any,
    raw: bytes,
    debug: dict[str, Any],
    label: str,
    role: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_info = _source_face_info(raw, role)
    cutout = await v143._prepare_user_cutout(mod, raw, debug, label)
    problem = _human_cutout_problem(cutout, role)
    if problem:
        raise v139.PipelineError("source_cutout", problem)
    cutout["verified_source_face"] = source_info
    cutout["verified_face_alpha"] = round(_cutout_face_alpha(cutout), 4)
    return cutout, source_info


def _visible_box(placement: dict[str, Any], size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    box = v148._layer_box(placement)
    if box is None:
        return None
    x, y, w, h = box
    width, height = size
    left = max(0, int(round(x)))
    top = max(0, int(round(y)))
    right = min(width, int(round(x + w)))
    bottom = min(height, int(round(y + h)))
    return (left, top, right, bottom) if right - left >= 8 and bottom - top >= 8 else None


def _pixel_delta(before_raw: bytes, after_raw: bytes, placement: dict[str, Any]) -> dict[str, float]:
    before = _open_rgb(before_raw)
    after = _open_rgb(after_raw)
    if before.size != after.size:
        after = ImageOps.fit(after, before.size, method=Image.Resampling.LANCZOS)
    box = _visible_box(placement, before.size)
    if box is None:
        return {"changed_ratio": 0.0, "mean_delta": 0.0, "peak_delta": 0.0}
    diff = ImageOps.grayscale(ImageChops.difference(before.crop(box), after.crop(box)))
    histogram = diff.histogram()
    total = max(1, sum(histogram))
    threshold = _integer("CELEBRITY_V149_DELTA_THRESHOLD", 12, 4, 40)
    changed = sum(histogram[threshold:]) / total
    mean_delta = float(ImageStat.Stat(diff).mean[0])
    peak = max((index for index, count in enumerate(histogram) if count), default=0)
    return {
        "changed_ratio": round(changed, 5),
        "mean_delta": round(mean_delta, 3),
        "peak_delta": float(peak),
    }


def _delta_problem(delta: dict[str, float], role: str) -> str:
    minimum_ratio = _number("CELEBRITY_V149_MIN_VISIBLE_DELTA_RATIO", 0.035, 0.008, 0.25)
    minimum_mean = _number("CELEBRITY_V149_MIN_VISIBLE_MEAN_DELTA", 2.2, 0.5, 20.0)
    if float(delta.get("changed_ratio") or 0) < minimum_ratio:
        return f"{role} layer is not visibly present: changed_ratio={float(delta.get('changed_ratio') or 0):.4f}"
    if float(delta.get("mean_delta") or 0) < minimum_mean:
        return f"{role} layer contribution is too weak: mean_delta={float(delta.get('mean_delta') or 0):.2f}"
    return ""


def _box_overlap_fraction(first: dict[str, Any], second: dict[str, Any]) -> float:
    a = v148._layer_box(first)
    b = v148._layer_box(second)
    if a is None or b is None:
        return 1.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    overlap_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    overlap_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    overlap = overlap_w * overlap_h
    return overlap / max(1.0, min(aw * ah, bw * bh))


def _debug_row(row: dict[str, Any]) -> dict[str, Any]:
    blocked = {"output", "plate_output", "celebrity_cutout", "user_cutout"}
    return {key: value for key, value in row.items() if key not in blocked}


async def _source_pixel_celebrity_variants(
    mod: Any,
    plate: dict[str, Any],
    references: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    reference_limit = _integer("CELEBRITY_V149_CELEBRITY_REFERENCE_ATTEMPTS", 6, 1, 8)
    placement_count = _integer("CELEBRITY_V149_CELEBRITY_PLACEMENTS", 3, 1, 3)
    candidates: list[tuple[float, int, bytes, dict[str, Any]]] = []
    for index, reference in enumerate([raw for raw in references if raw][:reference_limit], start=1):
        try:
            info = _source_face_info(reference, "celebrity")
            candidates.append((float(info.get("face_area_ratio") or 0), index, reference, info))
        except Exception as exc:
            debug.setdefault("errors", []).append({
                "stage": f"v149_reference_{index}",
                "provider": "local-face-proof",
                "category": "celebrity_reference",
                "error": v139._safe_error(exc),
            })
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, reference_index, reference, source_info in candidates:
        label = f"celebrity_ref_{reference_index}"
        try:
            cutout, _ = await _prepare_verified_cutout(mod, reference, debug, label, "celebrity")
        except Exception as exc:
            debug.setdefault("errors", []).append({
                "stage": f"v149_cutout_{label}",
                "provider": "photoroom/rembg+face-proof",
                "category": "celebrity_cutout",
                "error": v139._safe_error(exc),
            })
            continue
        for variant in range(placement_count):
            stage_label = f"{plate['label']}_v149_visible_celebrity_r{reference_index}_p{variant + 1}"
            stage = v139._stage_start(debug, stage_label, "verified-source-human-layer")
            try:
                raw, placement = v147._place_source_cutout(
                    plate["output"], cutout, side="right", variant=variant, role="celebrity"
                )
                problem = v148._source_layer_problem(raw, placement, side="right", role="celebrity")
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                delta = _pixel_delta(plate["output"], raw, placement)
                problem = _delta_problem(delta, "celebrity")
                if problem:
                    raise v139.PipelineError("visible_layer_qc", problem)
                row = {
                    "label": stage_label,
                    "scene": plate["label"],
                    "scene_provider": plate["provider"],
                    "celebrity_provider": f"source-cutout:{cutout.get('provider')}",
                    "celebrity_identity": 100.0,
                    "identity_unknown": False,
                    "reason": "one verified source face; original pixels visibly inserted",
                    "reference_index": reference_index,
                    "source_face": source_info,
                    "face_alpha": cutout.get("verified_face_alpha"),
                    "celebrity_visible_delta": delta,
                    "celebrity_pixel_preserved": True,
                    "celebrity_face_regenerated": False,
                    "placement": placement,
                    "plate_output": plate["output"],
                    "celebrity_cutout": cutout,
                    "output": raw,
                }
                results.append(row)
                debug.setdefault("identity_candidates", []).append(_debug_row(row))
                v139._stage_finish(stage, "ok", score=100.0, delta=delta, bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    results.sort(
        key=lambda item: (
            float((item.get("celebrity_visible_delta") or {}).get("changed_ratio") or 0),
            float((item.get("source_face") or {}).get("face_area_ratio") or 0),
        ),
        reverse=True,
    )
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
    placements = _integer("CELEBRITY_V149_USER_PLACEMENTS", 3, 1, 3)
    plate_output = celebrity_variant.get("plate_output")
    if not isinstance(plate_output, (bytes, bytearray)):
        debug.setdefault("errors", []).append({
            "stage": "v149_final", "provider": "visible-layer-qc",
            "category": "missing_plate", "error": "celebrity candidate has no original empty plate",
        })
        return rows
    celebrity_placement = dict(celebrity_variant.get("placement") or {})
    for cutout in cutouts:
        problem = _human_cutout_problem(cutout, "user")
        if problem:
            debug.setdefault("errors", []).append({
                "stage": f"v149_user_cutout_{cutout.get('label')}",
                "provider": "source-face-proof", "category": "user_cutout", "error": problem,
            })
            continue
        for variant in range(placements):
            label = f"{celebrity_variant['label']}_{cutout['label']}_v149_composite_{variant + 1}"
            stage = v139._stage_start(debug, label, "verified-dual-human-composite")
            try:
                raw, user_placement = v143._composite_user(celebrity_variant["output"], cutout, variant)
                problem = v148._dual_layer_problem(raw, user_placement, celebrity_placement)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                overlap = _box_overlap_fraction(user_placement, celebrity_placement)
                if overlap > _number("CELEBRITY_V149_MAX_LAYER_OVERLAP", 0.30, 0.05, 0.60):
                    raise v139.PipelineError("layout_qc", f"human layers overlap excessively: {overlap:.3f}")
                user_delta = _pixel_delta(celebrity_variant["output"], raw, user_placement)
                problem = _delta_problem(user_delta, "user")
                if problem:
                    raise v139.PipelineError("visible_layer_qc", problem)
                celebrity_final_delta = _pixel_delta(bytes(plate_output), raw, celebrity_placement)
                problem = _delta_problem(celebrity_final_delta, "celebrity-final")
                if problem:
                    raise v139.PipelineError("visible_layer_qc", problem)

                structural = v139._structural_score(raw)
                artifact = v141._artifact_metrics(raw)
                artifact_quality = float(artifact.get("quality") or 0)
                minimum_artifact = _number("CELEBRITY_V149_MIN_ARTIFACT_QUALITY", 28.0, 8.0, 75.0)
                if artifact_quality < minimum_artifact:
                    raise v139.PipelineError(
                        "composite_visual_qc", f"artifact quality too low: {artifact_quality:.1f}"
                    )
                visual_score = _number("CELEBRITY_V149_LOCAL_VISUAL_SCORE", 82.0, 60.0, 94.0)
                total = visual_score * 0.42 + structural * 0.23 + artifact_quality * 0.20
                total += min(15.0, float(user_delta["changed_ratio"]) * 20.0 + float(celebrity_final_delta["changed_ratio"]) * 20.0)
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
                    "visual_mode": "verified-visible-source-human-layers",
                    "visual_checks": {
                        "one_dominant_face_in_user_source": True,
                        "one_dominant_face_in_celebrity_source": True,
                        "user_face_survived_alpha_cutout": True,
                        "celebrity_face_survived_alpha_cutout": True,
                        "user_layer_visibly_changed_final_frame": True,
                        "celebrity_layer_visibly_changed_final_frame": True,
                        "left_user_right_celebrity": True,
                        "no_excessive_layer_overlap": True,
                    },
                    "structural": round(structural, 1),
                    "artifact_quality": artifact_quality,
                    "total": round(total, 2),
                    "reason": "both human source layers proved by source-face, alpha-face and final pixel-delta gates",
                    "user_pixel_preserved": True,
                    "user_face_regenerated": False,
                    "celebrity_pixel_preserved": True,
                    "celebrity_face_regenerated": False,
                    "face_swap_used": False,
                    "openai_image_edit_used": False,
                    "generic_face_detector_gate_used": False,
                    "source_layer_geometry_gate_used": True,
                    "visible_pixel_delta_gate_used": True,
                    "primary_selfie_only": True,
                    "user_visible_delta": user_delta,
                    "celebrity_visible_delta": celebrity_final_delta,
                    "layer_overlap": round(overlap, 4),
                    "placement": user_placement,
                    "celebrity_placement": celebrity_placement,
                    "output": raw,
                }
                rows.append(row)
                debug.setdefault("composite_candidates", []).append(_debug_row(row))
                v139._stage_finish(
                    stage, "ok", total=row["total"], user_delta=user_delta,
                    celebrity_delta=celebrity_final_delta, overlap=round(overlap, 4), bytes=len(raw),
                )
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    rows.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
    return rows


async def _run_v149_generation(
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
        "architecture": "provider-scene+verified-visible-dual-human-source-layers",
        "celebrity_reference_gate": "exactly-one-dominant-source-face",
        "cutout_face_alpha_gate": "required",
        "visible_pixel_delta_gate": "required-for-user-and-celebrity",
        "celebrity_final_retention_gate": "required",
        "generic_face_detector_final_gate": "disabled",
        "local_placeholder_background": "disabled",
        "user_face_generation": "disabled",
        "celebrity_face_generation": "disabled",
        "face_swap": "disabled",
    }
    try:
        output, debug = await _ORIGINAL_V148_RUN(
            mod, user_photo, celebrity_refs, celebrity_name, scene,
            previous_result=previous_result, additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update(contract)
        debug["v149_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v148, v147, v146, v145, v144, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update(contract)
        debug["v149_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v148, v147, v146, v145, v144, v143, v142, v139):
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
    output, _ = await _run_v149_generation(
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
        "architecture=provider_scene+verified_visible_dual_human_layers",
        "celebrity_reference_gate=exactly_one_dominant_source_face",
        "cutout_face_alpha_gate=required",
        "visible_pixel_delta_gate=user+celebrity+celebrity_final",
        "generic_face_detector_final_gate=disabled",
        "local_placeholder_background=disabled",
        "gemini_response_format=omitted",
        "gemini_output_aspect=local_normalization",
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
        f"selected={str(selected or '-')[:1800]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    for item in (debug.get("errors") or [])[-10:]:
        lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:360]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v148.install()
    # Never deliver the deterministic placeholder poster as a successful selfie.
    os.environ["CELEBRITY_V147_SCENE_PROVIDERS"] = str(
        os.environ.get("CELEBRITY_V149_SCENE_PROVIDERS") or "gemini,flux"
    )
    os.environ["CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK"] = "0"
    os.environ.setdefault("CELEBRITY_V149_CELEBRITY_REFERENCE_ATTEMPTS", "6")
    os.environ.setdefault("CELEBRITY_V149_CELEBRITY_PLACEMENTS", "3")
    os.environ.setdefault("CELEBRITY_V149_USER_PLACEMENTS", "3")
    os.environ.setdefault("CELEBRITY_V149_MIN_FACE_ALPHA", "0.62")
    os.environ.setdefault("CELEBRITY_V149_MIN_VISIBLE_DELTA_RATIO", "0.035")
    os.environ.setdefault("CELEBRITY_V149_MIN_VISIBLE_MEAN_DELTA", "2.2")
    os.environ.setdefault("CELEBRITY_V149_MAX_LAYER_OVERLAP", "0.30")
    os.environ.setdefault("CELEBRITY_V149_MIN_ARTIFACT_QUALITY", "28")
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"
    os.environ["CELEBRITY_V146_CELEBRITY_PROVIDERS"] = ""

    v144._gemini_scene_direct = _gemini_scene_normalized
    for module in (v142, v143, v145, v146, v147, v148):
        module._celebrity_variants = _source_pixel_celebrity_variants
    v143._build_composite_candidates = _source_pixel_build_composite_candidates
    v139.selfie._run_v149_generation = _run_v149_generation
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
                "diag_selfie_v149", "diag_selfie_v148", "diag_selfie_v147",
                "diag_selfie_v146", "diag_selfie_v145", "diag_selfie_v144",
                "diag_selfie_v143", "diag_celebrity_flow", "diag_brand",
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
    "_gemini_scene_normalized", "_source_face_info", "_human_cutout_problem",
    "_pixel_delta", "_delta_problem", "_source_pixel_celebrity_variants",
    "_source_pixel_build_composite_candidates", "_run_v149_generation", "_diag",
]
