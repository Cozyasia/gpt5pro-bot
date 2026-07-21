# -*- coding: utf-8 -*-
"""Celebrity Selfie v143: strict composite quality gate.

v142 proved that preserving the user's source pixels is the right direction, but
its first production build could accept a poorly segmented rectangular crop,
multiple unrelated people in the generated plate, and an unverified public-person
identity. v143 keeps the preserve-user architecture and makes every gate fail
closed:

* only the primary frontal selfie may be composited; the second angle is reference
  material only;
* PhotoRoom/rembg outputs must contain a genuinely non-rectangular alpha mask with
  transparent borders and corners;
* the generated plate must contain exactly one main foreground face on the right;
* the public-person identity must receive a real, non-unknown similarity score;
* the final frame must contain exactly two main foreground faces in the expected
  left-user/right-public-person layout;
* a vision quality gate rejects rectangular patches, leaked source backgrounds,
  extra people, incoherent scale/light and scene mismatch;
* the old generative fallback is disabled by default: returning no image is safer
  than delivering a visibly broken composite.
"""
from __future__ import annotations

import base64
import contextlib
import os
import time
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

import celebrity_selfie_v139 as v139
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142

VERSION = "v143-strict-composite-quality-gate-2026-07-21"
_GROUP = -2_100_000_600
_BUILDER_FLAG = "_celebrity_selfie_v143_builder"
_HANDLER_FLAG = "_celebrity_selfie_v143_handlers"

_ORIGINAL_FAILURE_MESSAGE = v139._failure_message
_ORIGINAL_V140_RUN = v142._ORIGINAL_V140_RUN
_LAST_RUN_DEBUG: dict[str, Any] = {}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float((os.environ.get(name) or str(default)).replace(",", "."))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return int(round(_number(name, float(default), float(minimum), float(maximum))))


def _open_rgb(raw: bytes) -> Image.Image:
    return v142._open_rgb(raw)


def _open_rgba(raw: bytes) -> Image.Image:
    return v142._open_rgba(raw)


def _encode_jpeg(image: Image.Image, quality: int = 96) -> bytes:
    return v142._encode_jpeg(image, quality=quality)


def _ratio_above(image: Image.Image, threshold: int) -> float:
    histogram = image.histogram()
    total = max(1, sum(histogram))
    return float(sum(histogram[max(0, threshold):])) / total


def _mean(image: Image.Image) -> float:
    return float(ImageStat.Stat(image).mean[0]) if image.width and image.height else 0.0


def _alpha_metrics(image: Image.Image) -> dict[str, Any]:
    alpha = image.getchannel("A")
    binary = alpha.point(lambda value: 255 if value >= 16 else 0)
    bbox = binary.getbbox()
    if not bbox:
        return {"bbox": None, "coverage": 0.0, "transparent": 1.0}

    width, height = alpha.size
    band_x = max(2, int(width * 0.035))
    band_y = max(2, int(height * 0.035))
    border_parts = [
        alpha.crop((0, 0, width, band_y)),
        alpha.crop((0, height - band_y, width, height)),
        alpha.crop((0, 0, band_x, height)),
        alpha.crop((width - band_x, 0, width, height)),
    ]
    border_pixels = sum(part.width * part.height for part in border_parts)
    border_opaque = sum(_ratio_above(part, 128) * part.width * part.height for part in border_parts) / max(1, border_pixels)

    corner_w = max(3, int(width * 0.09))
    corner_h = max(3, int(height * 0.09))
    corners = [
        alpha.crop((0, 0, corner_w, corner_h)),
        alpha.crop((width - corner_w, 0, width, corner_h)),
        alpha.crop((0, height - corner_h, corner_w, height)),
        alpha.crop((width - corner_w, height - corner_h, width, height)),
    ]
    corner_means = [_mean(part) for part in corners]
    transparent_corners = sum(value <= 45.0 for value in corner_means)

    bbox_alpha = alpha.crop(bbox)
    bbox_opaque = _ratio_above(bbox_alpha, 192)
    coverage = _mean(alpha) / 255.0
    transparent = 1.0 - _ratio_above(alpha, 16)
    bottom = alpha.crop((0, max(0, height - band_y), width, height))

    return {
        "bbox": list(bbox),
        "coverage": round(coverage, 4),
        "transparent": round(transparent, 4),
        "bbox_opaque": round(bbox_opaque, 4),
        "border_opaque": round(border_opaque, 4),
        "transparent_corners": int(transparent_corners),
        "corner_means": [round(value, 1) for value in corner_means],
        "bottom_opaque": round(_ratio_above(bottom, 128), 4),
        "bbox_width_ratio": round((bbox[2] - bbox[0]) / max(1, width), 4),
        "bbox_height_ratio": round((bbox[3] - bbox[1]) / max(1, height), 4),
    }


def _validate_cutout(raw: bytes) -> Image.Image:
    image = _open_rgba(raw)
    metrics = _alpha_metrics(image)
    if not metrics.get("bbox"):
        raise RuntimeError("background remover returned an empty alpha channel")

    coverage = float(metrics.get("coverage") or 0)
    transparent = float(metrics.get("transparent") or 0)
    bbox_opaque = float(metrics.get("bbox_opaque") or 0)
    border_opaque = float(metrics.get("border_opaque") or 0)
    transparent_corners = int(metrics.get("transparent_corners") or 0)
    full_frame = float(metrics.get("bbox_width_ratio") or 0) > 0.965 and float(metrics.get("bbox_height_ratio") or 0) > 0.965

    if coverage < _number("CELEBRITY_V143_ALPHA_MIN_COVERAGE", 0.035, 0.01, 0.20):
        raise RuntimeError(f"cutout subject coverage too small: {coverage:.3f}")
    if coverage > _number("CELEBRITY_V143_ALPHA_MAX_COVERAGE", 0.82, 0.55, 0.95):
        raise RuntimeError(f"cutout retained too much original background: coverage={coverage:.3f}")
    if transparent < _number("CELEBRITY_V143_ALPHA_MIN_TRANSPARENT", 0.10, 0.02, 0.45):
        raise RuntimeError(f"cutout has insufficient transparent background: {transparent:.3f}")
    if bbox_opaque > _number("CELEBRITY_V143_ALPHA_MAX_BBOX_OPAQUE", 0.84, 0.60, 0.97):
        raise RuntimeError(f"cutout mask is suspiciously rectangular: bbox_opaque={bbox_opaque:.3f}")
    if border_opaque > _number("CELEBRITY_V143_ALPHA_MAX_BORDER_OPAQUE", 0.48, 0.15, 0.80):
        raise RuntimeError(f"cutout leaks original background to image borders: border_opaque={border_opaque:.3f}")
    if transparent_corners < _integer("CELEBRITY_V143_ALPHA_MIN_CLEAR_CORNERS", 2, 1, 4):
        raise RuntimeError(f"cutout corners are not transparent enough: {transparent_corners}/4")
    if full_frame and transparent < 0.20:
        raise RuntimeError("cutout alpha bounding box covers the full source frame")
    return image


def _face_alpha_coverage(image: Image.Image, face: dict[str, Any] | None) -> float:
    if not face:
        return 0.0
    alpha = image.getchannel("A")
    x = max(0, int(float(face.get("x") or 0)))
    y = max(0, int(float(face.get("y") or 0)))
    right = min(image.width, int(float(face.get("x") or 0) + float(face.get("w") or 1)))
    bottom = min(image.height, int(float(face.get("y") or 0) + float(face.get("h") or 1)))
    if right <= x or bottom <= y:
        return 0.0
    return _mean(alpha.crop((x, y, right, bottom))) / 255.0


async def _prepare_user_cutout(mod: Any, raw: bytes, debug: dict[str, Any], label: str) -> dict[str, Any]:
    providers = [
        item.strip().casefold()
        for item in str(os.environ.get("CELEBRITY_V143_CUTOUT_PROVIDERS") or "photoroom,rembg").split(",")
        if item.strip()
    ]
    errors: list[str] = []
    result: bytes | None = None
    provider_used = ""
    image: Image.Image | None = None
    face = v142._largest_face(raw)

    for provider in providers:
        stage = v139._stage_start(debug, f"v143_cutout_{label}_{provider}", provider)
        try:
            if provider == "photoroom":
                old_size = os.environ.get("CELEBRITY_V142_PHOTOROOM_SIZE")
                os.environ["CELEBRITY_V142_PHOTOROOM_SIZE"] = str(os.environ.get("CELEBRITY_V143_PHOTOROOM_SIZE") or "hd")
                try:
                    result = await v142._photoroom_cutout(mod, raw)
                finally:
                    if old_size is None:
                        os.environ.pop("CELEBRITY_V142_PHOTOROOM_SIZE", None)
                    else:
                        os.environ["CELEBRITY_V142_PHOTOROOM_SIZE"] = old_size
            elif provider == "rembg":
                result = await v142._local_rembg_cutout(raw)
            else:
                continue
            image = _validate_cutout(result)
            face_coverage = _face_alpha_coverage(image, face)
            if face and face_coverage < _number("CELEBRITY_V143_FACE_ALPHA_MIN", 0.72, 0.40, 0.98):
                raise RuntimeError(f"segmentation removed too much of the user's face: {face_coverage:.3f}")
            metrics = _alpha_metrics(image)
            metrics["face_alpha"] = round(face_coverage, 4)
            v139._stage_finish(stage, "ok", bytes=len(result), **metrics)
            provider_used = provider
            break
        except Exception as exc:
            result = None
            image = None
            errors.append(f"{provider}:{v139._safe_error(exc)}")
            v139._record_error(debug, stage, exc)

    if result is None or image is None:
        raise v139.PipelineError(
            "user_cutout",
            "No background-removal provider returned a genuinely transparent person cutout: " + " | ".join(errors[-4:]),
            debug=debug,
        )

    alpha = image.getchannel("A").point(lambda value: 255 if value >= 16 else 0)
    bbox = alpha.getbbox()
    assert bbox is not None
    margin = _integer("CELEBRITY_V143_CUTOUT_MARGIN_PX", 10, 0, 50)
    bbox = (
        max(0, bbox[0] - margin),
        max(0, bbox[1] - margin),
        min(image.width, bbox[2] + margin),
        min(image.height, bbox[3] + margin),
    )
    trimmed = image.crop(bbox)
    relative_face: dict[str, float] | None = None
    if face:
        relative_face = {
            "x": float(face.get("x") or 0) - bbox[0],
            "y": float(face.get("y") or 0) - bbox[1],
            "w": float(face.get("w") or 1),
            "h": float(face.get("h") or 1),
        }
    metrics = _alpha_metrics(image)
    debug.setdefault("cutouts", []).append({
        "label": label,
        "provider": provider_used,
        "source_size": [image.width, image.height],
        "trimmed_size": [trimmed.width, trimmed.height],
        "alpha": metrics,
        "face": relative_face,
        "pixel_policy": "primary_source_pixels_only",
    })
    return {
        "label": label,
        "provider": provider_used,
        "image": trimmed,
        "face": relative_face,
        "source_raw": raw,
        "alpha_metrics": metrics,
    }


def _main_faces(raw: bytes) -> list[dict[str, Any]]:
    image = _open_rgb(raw)
    boxes = v142._face_boxes(raw)
    if not boxes:
        return []
    image_area = max(1.0, float(image.width * image.height))
    largest = max(float(row.get("w") or 0) * float(row.get("h") or 0) for row in boxes)
    absolute_floor = image_area * _number("CELEBRITY_V143_MAIN_FACE_AREA_RATIO", 0.006, 0.002, 0.03)
    relative_floor = largest * _number("CELEBRITY_V143_MAIN_FACE_RELATIVE_FLOOR", 0.22, 0.08, 0.60)
    floor = max(absolute_floor, relative_floor)
    return sorted(
        [row for row in boxes if float(row.get("w") or 0) * float(row.get("h") or 0) >= floor],
        key=lambda row: float(row.get("x") or 0),
    )


def _plate_problem(raw: bytes, label: str) -> str:
    try:
        metrics = v139._image_metrics(raw)
        if metrics["short_side"] < _number("CELEBRITY_V143_MIN_PLATE_SIDE", 640, 320, 1600):
            return "scene plate resolution too small"
        if metrics["brightness"] < 16 or metrics["brightness"] > 246 or metrics["contrast"] < 5:
            return "scene plate exposure or contrast unusable"
        image = _open_rgb(raw)
        faces = _main_faces(raw)
        if len(faces) != 1:
            return f"scene plate must contain exactly one main foreground face; found {len(faces)}"
        face = faces[0]
        cx = (float(face.get("x") or 0) + float(face.get("w") or 0) / 2.0) / max(1, image.width)
        cy = (float(face.get("y") or 0) + float(face.get("h") or 0) / 2.0) / max(1, image.height)
        area_ratio = (float(face.get("w") or 0) * float(face.get("h") or 0)) / max(1, image.width * image.height)
        if cx < _number("CELEBRITY_V143_RIGHT_FACE_MIN_X", 0.53, 0.42, 0.72):
            return "scene plate companion is not positioned on the right"
        if cy < 0.10 or cy > 0.62:
            return "scene plate companion face is vertically misplaced"
        if area_ratio < 0.006 or area_ratio > 0.18:
            return f"scene plate companion face scale is unsuitable: {area_ratio:.4f}"
        return ""
    except Exception as exc:
        return f"invalid strict scene plate: {v139._safe_error(exc)}"


async def _single_face_identity_score(mod: Any, output: bytes, reference: bytes) -> dict[str, Any]:
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision):
        return {"score": 0.0, "unknown": True, "reason": "strict vision QC unavailable"}
    ref = ImageOps.fit(_open_rgb(v139._face_crop(reference, 640)), (640, 640), method=Image.Resampling.LANCZOS)
    candidate = ImageOps.fit(_open_rgb(output), (900, 640), method=Image.Resampling.LANCZOS)
    board = v139._encode_board([ref, candidate], height=640)
    prompt = (
        "Strict quality-control board. LEFT panel is an identity reference. RIGHT panel is a generated scene plate. "
        "Do not identify or name anyone. The RIGHT panel must have exactly one main foreground adult, positioned on the right. "
        "Compare the LEFT reference only with that main face. Ignore tiny background portraits. Return strict JSON only with: "
        "similarity integer 0-100, exactly_one_main_foreground_face boolean, target_face_visible boolean, foreground_face_on_right "
        "boolean, extra_prominent_faces boolean, reason short string. Penalize changed head shape, hairline, eye spacing, nose, "
        "lips and jaw."
    )
    try:
        answer = await vision(prompt, base64.b64encode(board).decode("ascii"), "image/jpeg")
        data = v139._json_object(answer) or {}
        score = max(0.0, min(100.0, float(data.get("similarity") or 0)))
        valid = (
            data.get("exactly_one_main_foreground_face") is True
            and data.get("target_face_visible") is True
            and data.get("foreground_face_on_right") is True
            and data.get("extra_prominent_faces") is not True
        )
        if not valid or score <= 0:
            return {"score": 0.0, "unknown": True, "reason": str(data.get("reason") or "strict identity structure failed")[:350]}
        return {"score": round(score, 1), "unknown": False, "reason": str(data.get("reason") or "ok")[:350]}
    except Exception as exc:
        return {"score": 0.0, "unknown": True, "reason": f"strict-vision-qc-error:{v139._safe_error(exc)}"[:350]}


async def _celebrity_variants(
    mod: Any,
    plate: dict[str, Any],
    references: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    providers = [
        item.strip().casefold()
        for item in str(os.environ.get("CELEBRITY_V143_CELEBRITY_PROVIDERS") or "openai,piapi").split(",")
        if item.strip()
    ]
    results: list[dict[str, Any]] = []
    minimum = _number("CELEBRITY_V143_MIN_CELEBRITY_SCORE", 66.0, 45.0, 92.0)
    for provider in providers:
        if provider == "openai" and not v139.selfie._openai_key(mod):
            continue
        if provider == "piapi" and not v139.pi_identity._piapi_key(mod):
            continue
        label = f"{plate['label']}_v143_celebrity_{provider}"
        stage = v139._stage_start(debug, label, provider, side="right")
        try:
            if provider == "openai":
                raw = await v139._openai_single_face(
                    mod,
                    plate["output"],
                    references,
                    "right",
                    f"the selected PUBLIC PERSON ({celebrity_name})",
                    aspect,
                    repair=False,
                )
            elif provider == "piapi":
                raw = await v142._piapi_celebrity(mod, plate["output"], references[0])
            else:
                continue
            problem = _plate_problem(raw, label)
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            qc = await _single_face_identity_score(mod, raw, references[0])
            score = float(qc.get("score") or 0)
            if qc.get("unknown") or score < minimum:
                raise v139.PipelineError("celebrity_identity", f"strict celebrity score {score:.1f} below {minimum:.1f}: {qc.get('reason')}")
            row = {
                "label": label,
                "scene": plate["label"],
                "scene_provider": plate["provider"],
                "celebrity_provider": provider,
                "celebrity_identity": round(score, 1),
                "identity_unknown": False,
                "reason": qc.get("reason"),
                "output": raw,
            }
            results.append(row)
            debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
            v139._stage_finish(stage, "ok", score=round(score, 1), unknown=False, bytes=len(raw))
            if score >= _number("CELEBRITY_V143_CELEBRITY_STOP_SCORE", 80.0, minimum, 97.0):
                break
        except Exception as exc:
            v139._record_error(debug, stage, exc)
    results.sort(key=lambda item: float(item.get("celebrity_identity") or 0), reverse=True)
    return results


def _composite_user(scene_raw: bytes, cutout_info: dict[str, Any], variant: int) -> tuple[bytes, dict[str, Any]]:
    scene = _open_rgb(scene_raw)
    width, height = scene.size
    face_fraction = _number("CELEBRITY_V143_USER_FACE_HEIGHT", 0.285, 0.20, 0.36)
    resized, face = v142._resize_cutout(cutout_info, scene.size, face_fraction)

    targets = ((0.255, 0.315), (0.235, 0.335), (0.275, 0.335))
    target_x, target_y = targets[variant % len(targets)]
    face_cx = float(face.get("x") or resized.width * 0.5) + float(face.get("w") or 0) / 2.0 if face else resized.width * 0.5
    face_cy = float(face.get("y") or resized.height * 0.24) + float(face.get("h") or 0) / 2.0 if face else resized.height * 0.24
    x = int(width * target_x - face_cx)
    y = int(height * target_y - face_cy)
    x = max(-int(width * 0.06), min(x, int(width * 0.49) - resized.width))
    y = max(-int(height * 0.04), min(y, height - int(resized.height * 0.60)))

    alpha = resized.getchannel("A")
    bottom_band = alpha.crop((0, max(0, alpha.height - max(2, int(alpha.height * 0.025))), alpha.width, alpha.height))
    bottom_opaque = _ratio_above(bottom_band, 96)
    bottom_anchored = bottom_opaque > 0.08
    if bottom_anchored:
        y = max(y, height - resized.height + int(height * 0.012))

    region_box = (max(0, x), max(0, y), min(width, x + resized.width), min(height, y + resized.height))
    region = scene.crop(region_box)
    if region.size != resized.size:
        region = ImageOps.fit(region, resized.size, method=Image.Resampling.LANCZOS)
    resized = v142._harmonise_cutout(resized, region, face)

    alpha = resized.getchannel("A")
    feather = _number("CELEBRITY_V143_EDGE_FEATHER_PX", 0.9, 0.0, 3.0)
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    resized.putalpha(alpha)

    canvas = scene.convert("RGBA")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(_number("CELEBRITY_V143_SHADOW_BLUR", 10.0, 2.0, 24.0)))
    shadow_alpha = shadow_alpha.point(lambda value: int(value * _number("CELEBRITY_V143_SHADOW_OPACITY", 0.14, 0.0, 0.35)))
    shadow = Image.new("RGBA", resized.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    canvas.alpha_composite(shadow, (x + 4, y + 6))
    canvas.alpha_composite(resized, (x, y))

    metadata = {
        "cutout_provider": cutout_info.get("provider"),
        "cutout_label": cutout_info.get("label"),
        "placement_variant": variant,
        "position": [x, y],
        "size": [resized.width, resized.height],
        "bottom_anchored": bottom_anchored,
        "bottom_opaque": round(bottom_opaque, 4),
        "alpha_metrics": cutout_info.get("alpha_metrics"),
        "user_pixel_policy": "primary_source_pixels_preserved_no_generation",
        "face_geometry_lock": True,
    }
    return _encode_jpeg(canvas), metadata


def _final_layout_problem(raw: bytes) -> str:
    image = _open_rgb(raw)
    faces = _main_faces(raw)
    if len(faces) != 2:
        return f"final frame must contain exactly two main foreground faces; found {len(faces)}"
    left, right = faces
    left_cx = (float(left.get("x") or 0) + float(left.get("w") or 0) / 2.0) / max(1, image.width)
    right_cx = (float(right.get("x") or 0) + float(right.get("w") or 0) / 2.0) / max(1, image.width)
    if left_cx >= right_cx or left_cx > 0.54 or right_cx < 0.46:
        return "final face layout is not left-user/right-celebrity"
    left_area = max(1.0, float(left.get("w") or 1) * float(left.get("h") or 1))
    right_area = max(1.0, float(right.get("w") or 1) * float(right.get("h") or 1))
    ratio = left_area / right_area
    if ratio < 0.38 or ratio > 2.60:
        return f"final foreground face scales are incompatible: {ratio:.2f}"
    return ""


async def _visual_composite_qc(mod: Any, raw: bytes, user_ref: bytes, scene: str) -> dict[str, Any]:
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision):
        return {"accepted": False, "score": 0.0, "reason": "strict visual composite QC unavailable", "unknown": True}
    source = ImageOps.fit(_open_rgb(user_ref), (520, 640), method=Image.Resampling.LANCZOS)
    result = ImageOps.fit(_open_rgb(raw), (900, 640), method=Image.Resampling.LANCZOS)
    board = v139._encode_board([source, result], height=640)
    prompt = (
        "Strict compositing quality-control board. LEFT panel is the user's original selfie and may contain a car/interior or "
        "other source background. RIGHT panel is the final AI selfie. Do not identify or name anyone. The RIGHT panel must show "
        "exactly two main foreground adults: the preserved user naturally on the LEFT and one generated companion on the RIGHT. "
        "The user's original background must NOT appear as a rectangle, box, panel or leaked patch in the RIGHT image. Check scale, "
        "lighting, edges, body placement and scene continuity. Requested scene description: " + str(scene)[:300] + ". Return strict "
        "JSON only with: exactly_two_main_people boolean, user_identity_matches_source boolean, no_rectangular_patch boolean, "
        "no_source_background_leak boolean, coherent_scale boolean, coherent_lighting boolean, clean_cutout_edges boolean, "
        "companion_face_visible boolean, no_extra_prominent_people boolean, scene_matches_request boolean, naturalness integer 0-100, "
        "reason short string."
    )
    try:
        answer = await vision(prompt, base64.b64encode(board).decode("ascii"), "image/jpeg")
        data = v139._json_object(answer) or {}
        score = max(0.0, min(100.0, float(data.get("naturalness") or 0)))
        checks = {
            "exactly_two_main_people": data.get("exactly_two_main_people") is True,
            "user_identity_matches_source": data.get("user_identity_matches_source") is True,
            "no_rectangular_patch": data.get("no_rectangular_patch") is True,
            "no_source_background_leak": data.get("no_source_background_leak") is True,
            "coherent_scale": data.get("coherent_scale") is True,
            "coherent_lighting": data.get("coherent_lighting") is True,
            "clean_cutout_edges": data.get("clean_cutout_edges") is True,
            "companion_face_visible": data.get("companion_face_visible") is True,
            "no_extra_prominent_people": data.get("no_extra_prominent_people") is True,
            "scene_matches_request": data.get("scene_matches_request") is True,
        }
        minimum = _number("CELEBRITY_V143_MIN_VISUAL_NATURALNESS", 70.0, 45.0, 95.0)
        accepted = all(checks.values()) and score >= minimum
        return {
            "accepted": accepted,
            "score": round(score, 1),
            "minimum": minimum,
            "checks": checks,
            "reason": str(data.get("reason") or ("ok" if accepted else "strict composite checks failed"))[:500],
            "unknown": False,
        }
    except Exception as exc:
        return {"accepted": False, "score": 0.0, "reason": f"visual-qc-error:{v139._safe_error(exc)}"[:500], "unknown": True}


async def _build_composite_candidates(
    mod: Any,
    celebrity_variant: dict[str, Any],
    cutouts: list[dict[str, Any]],
    user_ref: bytes,
    celebrity_ref: bytes,
    scene: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    placements = _integer("CELEBRITY_V143_PLACEMENT_VARIANTS", 2, 1, 3)
    minimum_celebrity = _number("CELEBRITY_V143_MIN_CELEBRITY_SCORE", 66.0, 45.0, 92.0)
    for cutout in cutouts:
        for variant in range(placements):
            label = f"{celebrity_variant['label']}_{cutout['label']}_v143_composite_{variant + 1}"
            stage = v139._stage_start(debug, label, "strict-local-composite")
            try:
                raw, placement = _composite_user(celebrity_variant["output"], cutout, variant)
                problem = _final_layout_problem(raw)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                visual = await _visual_composite_qc(mod, raw, user_ref, scene)
                if not visual.get("accepted"):
                    raise v139.PipelineError("composite_visual_qc", str(visual.get("reason") or "strict visual QC rejected result"))
                identity = await v139._final_identity_qc(mod, raw, user_ref, celebrity_ref)
                measured_user = float(identity.get("user") or 0)
                measured_celebrity = float(identity.get("celebrity") or 0)
                variant_score = float(celebrity_variant.get("celebrity_identity") or 0)
                celebrity_score = min(variant_score, measured_celebrity) if measured_celebrity > 0 and not identity.get("unknown") else variant_score
                if celebrity_score < minimum_celebrity:
                    raise v139.PipelineError("celebrity_identity", f"final celebrity score {celebrity_score:.1f} below {minimum_celebrity:.1f}")
                user_score = 100.0
                structural = v139._structural_score(raw)
                artifact = v141._artifact_metrics(raw)
                total = celebrity_score * 0.36 + float(visual.get("score") or 0) * 0.34 + structural * 0.12 + float(artifact.get("quality") or 0) * 0.18
                row = {
                    "label": label,
                    "scene": celebrity_variant.get("scene"),
                    "scene_provider": celebrity_variant.get("scene_provider"),
                    "user_provider": f"cutout:{cutout.get('provider')}",
                    "celebrity_provider": celebrity_variant.get("celebrity_provider"),
                    "user_identity": user_score,
                    "user_identity_measured": round(measured_user, 1),
                    "celebrity_identity": round(celebrity_score, 1),
                    "identity_min": round(min(user_score, celebrity_score), 1),
                    "identity_weighted": round(user_score * 0.58 + celebrity_score * 0.42, 1),
                    "identity_unknown": False,
                    "visual_naturalness": float(visual.get("score") or 0),
                    "visual_checks": visual.get("checks"),
                    "structural": round(structural, 1),
                    "artifact_quality": float(artifact.get("quality") or 0),
                    "total": round(total, 2),
                    "reason": str(visual.get("reason") or identity.get("reason") or "ok")[:500],
                    "user_pixel_preserved": True,
                    "user_face_regenerated": False,
                    "primary_selfie_only": True,
                    "placement": placement,
                    "output": raw,
                }
                rows.append(row)
                debug.setdefault("composite_candidates", []).append({key: value for key, value in row.items() if key != "output"})
                v139._stage_finish(stage, "ok", total=row["total"], celebrity=row["celebrity_identity"], naturalness=row["visual_naturalness"], bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    rows.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
    return rows


async def _run_v143_generation(
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
    if not user_photo:
        raise v139.PipelineError("input", "User selfie is missing")
    if not celebrity_refs:
        raise v139.PipelineError("input", "Public-person references are missing")

    aspect = v139.selfie._aspect_for_scene(scene)
    debug = v139._new_debug(celebrity_name, scene, aspect)
    debug.update({
        "version": VERSION,
        "architecture": "strict_right_plate+verified_celebrity+primary_source_cutout+vision_composite_qc",
        "user_generation": "disabled",
        "primary_selfie_only": True,
        "second_user_angle_role": "reference_only",
        "user_pixel_lock": "source_pixels_first",
        "nano_banana_comet": "disabled",
        "cutouts": [],
        "composite_candidates": [],
        "legacy_fallback": None,
    })
    best_public_ref = await v139.selfie.impl._best_reference(celebrity_refs)
    public_refs = [best_public_ref, *[raw for raw in celebrity_refs if raw is not best_public_ref]]

    try:
        cutout = await _prepare_user_cutout(mod, user_photo, debug, "primary_user")
        cutouts = [cutout]
        plates = await v142._make_plate_candidates(mod, scene, aspect, user_photo, debug)
        strict_plates: list[dict[str, Any]] = []
        for plate in plates:
            problem = _plate_problem(plate["output"], str(plate.get("label") or "plate"))
            if not problem:
                strict_plates.append(plate)
            else:
                debug["errors"].append({"stage": plate.get("label"), "provider": plate.get("provider"), "category": "structural_qc", "error": problem})
        if not strict_plates:
            raise v139.PipelineError("scene_generation", "No one-person right-side scene plate survived strict checks", debug=debug)

        finals: list[dict[str, Any]] = []
        celebrity_count = 0
        plate_limit = _integer("CELEBRITY_V143_PLATES_TO_IDENTITY", 2, 1, 3)
        for plate in strict_plates[:plate_limit]:
            celebrities = await _celebrity_variants(mod, plate, public_refs, celebrity_name, aspect, debug)
            celebrity_count += len(celebrities)
            for celebrity_variant in celebrities[:2]:
                finals.extend(await _build_composite_candidates(
                    mod,
                    celebrity_variant,
                    cutouts,
                    user_photo,
                    best_public_ref,
                    scene,
                    debug,
                ))
        if celebrity_count == 0:
            raise v139.PipelineError("celebrity_identity", "No verified public-person identity candidate survived", debug=debug)
        if not finals:
            raise v139.PipelineError("composite_visual_qc", "No composite survived the strict layout and visual quality gates", debug=debug)

        best = finals[0]
        debug["selected"] = {key: value for key, value in best.items() if key != "output"}
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        debug["failure_class"] = None
        public = v139._public_debug(debug)
        public["cutouts"] = debug.get("cutouts", [])[-2:]
        public["composite_candidates"] = debug.get("composite_candidates", [])[-8:]
        public["legacy_fallback"] = None
        _LAST_RUN_DEBUG = public
        v142._LAST_RUN_DEBUG = public
        v139._LAST_RUN_DEBUG = public
        return best["output"], public
    except Exception as exc:
        if _flag("CELEBRITY_V143_LEGACY_FALLBACK", False):
            stage = v139._stage_start(debug, "v143_explicit_legacy_fallback", "v140")
            try:
                output, fallback_debug = await _ORIGINAL_V140_RUN(
                    mod,
                    user_photo,
                    celebrity_refs,
                    celebrity_name,
                    scene,
                    previous_result=previous_result,
                    additional_user_refs=additional_user_refs,
                )
                debug["legacy_fallback"] = "used-explicitly"
                debug["selected"] = dict(fallback_debug.get("selected") or {})
                debug["selected"].update({
                    "user_pixel_preserved": False,
                    "user_face_regenerated": True,
                    "pipeline": "v140-explicit-legacy-fallback",
                })
                v139._stage_finish(stage, "ok", bytes=len(output))
                public = v139._public_debug(debug)
                public["legacy_fallback"] = "used-explicitly"
                _LAST_RUN_DEBUG = public
                v142._LAST_RUN_DEBUG = public
                v139._LAST_RUN_DEBUG = public
                return output, public
            except Exception as fallback_exc:
                v139._record_error(debug, stage, fallback_exc)
        category = getattr(exc, "category", None) or v139._classify_error(exc)
        debug["failure_class"] = category
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        public = v139._public_debug(debug)
        public["cutouts"] = debug.get("cutouts", [])[-2:]
        public["composite_candidates"] = debug.get("composite_candidates", [])[-8:]
        public["legacy_fallback"] = debug.get("legacy_fallback")
        _LAST_RUN_DEBUG = public
        v142._LAST_RUN_DEBUG = public
        v139._LAST_RUN_DEBUG = public
        if isinstance(exc, v139.PipelineError):
            exc.debug = public
            raise
        raise v139.PipelineError(category, v139._safe_error(exc), debug=public) from exc


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
    output, _ = await _run_v143_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def _failure_message(exc: BaseException, debug: dict[str, Any]) -> str:
    category = getattr(exc, "category", None) or debug.get("failure_class") or v139._classify_error(exc)
    messages = {
        "user_cutout": "Фон исходного селфи не был удалён достаточно чисто; прямоугольный фрагмент не будет отправлен.",
        "scene_generation": "Не удалось получить сцену ровно с одной основной персоной справа и свободным местом слева.",
        "celebrity_identity": "Ни один вариант выбранной персоны не прошёл строгую проверку сходства.",
        "composite_visual_qc": "Готовая склейка не прошла проверку естественности, краёв, фона, количества людей или соответствия сцене.",
        "structural_qc": "Кадр не прошёл проверку структуры и расположения двух главных лиц.",
    }
    return messages.get(str(category), _ORIGINAL_FAILURE_MESSAGE(exc, debug))


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or _LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    mod = v139.selfie.engine._runtime_module()
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=strict_right_plate+verified_celebrity+primary_source_cutout+vision_composite_qc",
        "user_face_generation=disabled",
        "primary_selfie_only=1",
        "second_angle=reference_only",
        "rectangular_cutout=blocked",
        "extra_main_people=blocked",
        "unknown_celebrity_identity=blocked",
        "visual_composite_qc=required",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"photoroom={'ready' if (mod is not None and bool(v142._photoroom_key(mod))) else 'missing'}",
        f"local_rembg={'enabled' if v142._flag('CELEBRITY_V142_LOCAL_REMBG_FALLBACK', True) else 'disabled'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"cutouts={str(debug.get('cutouts') or '-')[:1500]}",
        f"legacy_fallback={debug.get('legacy_fallback') or '-'}",
        f"delivery_mode={session.get('delivery_mode') or '-'}",
        f"selected={str(selected or '-')[:1800]}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    errors = debug.get("errors") or []
    if errors:
        lines.append("errors:")
        for item in errors[-10:]:
            lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:320]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    os.environ.setdefault("CELEBRITY_V143_CUTOUT_PROVIDERS", "photoroom,rembg")
    os.environ.setdefault("CELEBRITY_V143_PHOTOROOM_SIZE", "hd")
    os.environ.setdefault("CELEBRITY_V143_ALPHA_MAX_COVERAGE", "0.82")
    os.environ.setdefault("CELEBRITY_V143_ALPHA_MIN_TRANSPARENT", "0.10")
    os.environ.setdefault("CELEBRITY_V143_ALPHA_MAX_BBOX_OPAQUE", "0.84")
    os.environ.setdefault("CELEBRITY_V143_ALPHA_MAX_BORDER_OPAQUE", "0.48")
    os.environ.setdefault("CELEBRITY_V143_ALPHA_MIN_CLEAR_CORNERS", "2")
    os.environ.setdefault("CELEBRITY_V143_MIN_CELEBRITY_SCORE", "66")
    os.environ.setdefault("CELEBRITY_V143_MIN_VISUAL_NATURALNESS", "70")
    os.environ.setdefault("CELEBRITY_V143_PLATES_TO_IDENTITY", "2")
    os.environ.setdefault("CELEBRITY_V143_PLACEMENT_VARIANTS", "2")
    os.environ.setdefault("CELEBRITY_V143_LEGACY_FALLBACK", "0")
    os.environ["CELEBRITY_V142_USER_CUTOUTS"] = "1"
    os.environ["CELEBRITY_V142_LEGACY_FALLBACK"] = "0"
    os.environ["CELEBRITY_V141_OPENAI_QUALITY_CLEANUP"] = "0"

    v142.VERSION = VERSION
    v142._validate_cutout = _validate_cutout
    v142._prepare_user_cutout = _prepare_user_cutout
    v142._plate_problem = _plate_problem
    v142._single_face_identity_score = _single_face_identity_score
    v142._celebrity_variants = _celebrity_variants
    v142._composite_user = _composite_user
    v142._final_layout_problem = _final_layout_problem
    v142._run_v142_generation = _run_v143_generation
    v142._run_compat = _run_compat
    v139.VERSION = VERSION
    v139._run_two_stage_generation = _run_v143_generation
    v139._failure_message = _failure_message
    v139.selfie._run_v142_generation = _run_v143_generation
    v139.selfie._run_v143_generation = _run_v143_generation
    v139.selfie._generate = v142._generate
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._generate = v142._generate
    v139.selfie.engine._result_kb = v142._result_kb
    v139.selfie.engine._diag = _diag
    v141._generate = v142._generate
    v141._result_kb = v142._result_kb


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
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v143",
                "diag_selfie_v142",
                "diag_selfie_v141",
                "diag_selfie_v139",
                "diag_celebrity_flow",
                "diag_brand",
            ):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


install()

__all__ = [
    "VERSION",
    "install",
    "install_builder_hook",
    "_alpha_metrics",
    "_validate_cutout",
    "_prepare_user_cutout",
    "_main_faces",
    "_plate_problem",
    "_single_face_identity_score",
    "_celebrity_variants",
    "_composite_user",
    "_final_layout_problem",
    "_visual_composite_qc",
    "_build_composite_candidates",
    "_run_v143_generation",
    "_diag",
]
