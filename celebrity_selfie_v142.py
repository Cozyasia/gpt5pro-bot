# -*- coding: utf-8 -*-
"""Celebrity Selfie v142: preserve-user compositing pipeline.

The user's face is no longer regenerated in the normal route.  v142 builds a
scene plate with one anonymous RIGHT-side person, locks only the selected public
person's identity, removes the background from the user's real selfie, and
composites the original user pixels into the LEFT foreground.  Only local
photographic harmonisation (scale, mild exposure match, feathered edges and
shadow) is allowed on the user cutout; face geometry is never synthesised.

PhotoRoom's segmentation endpoint is preferred when configured.  Local rembg is
an explicit fallback.  The previous v140 scene-first/two-face route remains a
last-resort reliability fallback and is clearly marked in diagnostics.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import time
import uuid
from io import BytesIO
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import celebrity_selfie_v141 as v141
import ui_selfie_v138 as ui138

VERSION = "v142-preserve-user-composite-2026-07-21"
_GROUP = -2_100_000_500
_BUILDER_FLAG = "_celebrity_selfie_v142_builder"
_HANDLER_FLAG = "_celebrity_selfie_v142_handlers"

_ORIGINAL_V140_RUN = v140._run_v140_generation
_ORIGINAL_V141_RESULT_KB = v141._result_kb

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
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _open_rgba(raw: bytes) -> Image.Image:
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGBA")


def _encode_jpeg(image: Image.Image, quality: int = 96) -> bytes:
    output = BytesIO()
    image.convert("RGB").save(output, "JPEG", quality=quality, optimize=True, progressive=True)
    return output.getvalue()


def _encode_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.convert("RGBA").save(output, "PNG", optimize=True)
    return output.getvalue()


def _runtime_value(mod: Any, name: str, default: str = "") -> str:
    return str(getattr(mod, name, "") or os.environ.get(name) or default).strip()


def _photoroom_key(mod: Any) -> str:
    return _runtime_value(mod, "PHOTOROOM_API_KEY")


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    return image.getchannel("A").getbbox()


def _validate_cutout(raw: bytes) -> Image.Image:
    image = _open_rgba(raw)
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        raise RuntimeError("background remover returned an empty alpha channel")
    coverage = float(ImageStat.Stat(alpha).mean[0]) / 255.0
    if coverage < 0.02 or coverage > 0.92:
        raise RuntimeError(f"background remover alpha coverage is implausible: {coverage:.3f}")
    return image


async def _photoroom_cutout(mod: Any, raw: bytes) -> bytes:
    key = _photoroom_key(mod)
    if not key:
        raise RuntimeError("PHOTOROOM_API_KEY missing")
    base = _runtime_value(mod, "PHOTOROOM_BASE_URL", "https://sdk.photoroom.com").rstrip("/")
    path = _runtime_value(mod, "PHOTOROOM_REMOVE_PATH", "/v1/segment")
    if not path.startswith("/"):
        path = "/" + path
    timeout_s = _integer("CELEBRITY_V142_PHOTOROOM_TIMEOUT_S", 90, 20, 240)
    fields = {
        "format": "png",
        "channels": "rgba",
        "size": str(os.environ.get("CELEBRITY_V142_PHOTOROOM_SIZE") or "full"),
        "crop": "false",
    }
    files = {"image_file": ("user-selfie.jpg", raw, "image/jpeg")}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=25, read=timeout_s, write=90),
        follow_redirects=True,
    ) as client:
        response = await client.post(base + path, headers={"x-api-key": key}, data=fields, files=files)
    if response.status_code >= 400:
        raise RuntimeError(f"PhotoRoom segment HTTP {response.status_code}: {response.text[:450]}")
    _validate_cutout(response.content)
    return response.content


async def _local_rembg_cutout(raw: bytes) -> bytes:
    if not _flag("CELEBRITY_V142_LOCAL_REMBG_FALLBACK", True):
        raise RuntimeError("local rembg fallback disabled")

    def run() -> bytes:
        from rembg import remove

        result = remove(raw)
        if not isinstance(result, (bytes, bytearray)):
            raise RuntimeError("rembg returned no bytes")
        return bytes(result)

    timeout_s = _integer("CELEBRITY_V142_REMBG_TIMEOUT_S", 240, 30, 600)
    result = await asyncio.wait_for(asyncio.to_thread(run), timeout=timeout_s)
    _validate_cutout(result)
    return result


def _face_boxes(raw: bytes) -> list[dict[str, Any]]:
    with contextlib.suppress(Exception):
        rows = v139.selfie.base._face_boxes(raw)
        return [dict(item) for item in (rows or []) if isinstance(item, dict)]
    return []


def _largest_face(raw: bytes) -> dict[str, Any] | None:
    rows = _face_boxes(raw)
    if not rows:
        return None
    return max(rows, key=lambda item: float(item.get("w") or 0) * float(item.get("h") or 0))


async def _prepare_user_cutout(mod: Any, raw: bytes, debug: dict[str, Any], label: str) -> dict[str, Any]:
    providers = [item.strip().casefold() for item in str(os.environ.get("CELEBRITY_V142_CUTOUT_PROVIDERS") or "photoroom,rembg").split(",") if item.strip()]
    errors: list[str] = []
    result: bytes | None = None
    provider_used = ""
    for provider in providers:
        stage = v139._stage_start(debug, f"cutout_{label}_{provider}", provider)
        try:
            if provider == "photoroom":
                result = await _photoroom_cutout(mod, raw)
            elif provider == "rembg":
                result = await _local_rembg_cutout(raw)
            else:
                continue
            image = _validate_cutout(result)
            v139._stage_finish(stage, "ok", bytes=len(result), coverage=round(float(ImageStat.Stat(image.getchannel("A")).mean[0]) / 255.0, 3))
            provider_used = provider
            break
        except Exception as exc:
            errors.append(f"{provider}:{v139._safe_error(exc)}")
            v139._record_error(debug, stage, exc)
    if not result:
        raise v139.PipelineError("user_cutout", "No background-removal provider returned a usable user cutout: " + " | ".join(errors[-3:]), debug=debug)

    image = _validate_cutout(result)
    bbox = _alpha_bbox(image)
    assert bbox is not None
    margin = _integer("CELEBRITY_V142_CUTOUT_MARGIN_PX", 18, 0, 80)
    bbox = (
        max(0, bbox[0] - margin),
        max(0, bbox[1] - margin),
        min(image.width, bbox[2] + margin),
        min(image.height, bbox[3] + margin),
    )
    trimmed = image.crop(bbox)
    face = _largest_face(raw)
    relative_face: dict[str, float] | None = None
    if face:
        relative_face = {
            "x": float(face.get("x") or 0) - bbox[0],
            "y": float(face.get("y") or 0) - bbox[1],
            "w": float(face.get("w") or 1),
            "h": float(face.get("h") or 1),
        }
    debug.setdefault("cutouts", []).append({
        "label": label,
        "provider": provider_used,
        "source_size": [image.width, image.height],
        "trimmed_size": [trimmed.width, trimmed.height],
        "alpha_bbox": list(bbox),
        "face": relative_face,
        "pixel_policy": "source_pixels_only",
    })
    return {
        "label": label,
        "provider": provider_used,
        "image": trimmed,
        "face": relative_face,
        "source_raw": raw,
    }


def _lighting_hint(raw: bytes) -> str:
    image = ImageOps.fit(_open_rgb(raw), (256, 256), method=Image.Resampling.LANCZOS)
    stat = ImageStat.Stat(image)
    r, g, b = [float(value) for value in stat.mean[:3]]
    lum = (r + g + b) / 3.0
    warmth = r - b
    exposure = "soft low-key" if lum < 85 else "balanced natural" if lum < 165 else "bright soft"
    temperature = "warm-neutral" if warmth > 12 else "cool-neutral" if warmth < -12 else "neutral"
    return f"{exposure}, {temperature} frontal smartphone lighting"


def _scene_prompt(scene: str, aspect: str, variant: int, lighting: str) -> str:
    framings = (
        "arm-length smartphone selfie framing with a close RIGHT-side companion",
        "candid shoulder-level phone photograph with the RIGHT companion leaning slightly inward",
        "premium editorial smartphone selfie with a natural RIGHT-side companion and environmental context",
    )
    return (
        "Create ONE seamless photorealistic smartphone photograph that will be used as a compositing plate. "
        "Exactly ONE anonymous adult is present, positioned entirely in the RIGHT half of the image. The RIGHT person's face "
        "is large, unobstructed, front-facing or gentle three-quarter view, naturally looking into the phone camera, with upper "
        "torso visible and shoulders angled slightly toward the empty left side. The LEFT foreground must remain intentionally "
        "empty and visually clean, reserved for compositing a real user later: no person, face, body, arm, reflection, portrait, "
        "poster or phone-screen face may appear in the LEFT half. Keep enough realistic floor, seat or background continuity "
        "behind that empty area. Camera perspective: the unseen future LEFT person is holding the phone at arm length. "
        f"Framing: {framings[variant % len(framings)]}. Scene: {v139.selfie.v134._scene_profile(scene)} "
        f"Lighting must be coherent with a future inserted person: {lighting}. Use natural mobile HDR, realistic skin, correct "
        "hands and body anatomy, subtle depth of field and one shared light direction. No second person, no duplicate face, no "
        "crowd face, no collage, split screen, contact sheet, inset, border, text, logo or watermark. "
        f"Aspect ratio {aspect}. Return only the final image."
    )


def _plate_problem(raw: bytes, label: str) -> str:
    try:
        metrics = v139._image_metrics(raw)
        if metrics["short_side"] < _number("CELEBRITY_V142_MIN_PLATE_SIDE", 640, 320, 1600):
            return "scene plate resolution too small"
        if metrics["brightness"] < 16 or metrics["brightness"] > 246:
            return "scene plate exposure unusable"
        if metrics["contrast"] < 5:
            return "scene plate contrast unusable"
        image = _open_rgb(raw)
        boxes = _face_boxes(raw)
        if len(boxes) > 2:
            return "scene plate contains extra foreground faces"
        if boxes:
            primary = max(boxes, key=lambda item: float(item.get("w") or 0) * float(item.get("h") or 0))
            cx = (float(primary.get("x") or 0) + float(primary.get("w") or 0) / 2.0) / max(1, image.width)
            if cx < _number("CELEBRITY_V142_RIGHT_FACE_MIN_X", 0.50, 0.38, 0.75):
                return "scene plate companion is not positioned on the right"
        return ""
    except Exception as exc:
        return f"invalid scene plate: {v139._safe_error(exc)}"


def _plate_score(raw: bytes) -> float:
    score = v139._structural_score(raw)
    image = _open_rgb(raw)
    boxes = _face_boxes(raw)
    if boxes:
        primary = max(boxes, key=lambda item: float(item.get("w") or 0) * float(item.get("h") or 0))
        cx = (float(primary.get("x") or 0) + float(primary.get("w") or 0) / 2.0) / max(1, image.width)
        score += max(0.0, 30.0 - abs(cx - 0.72) * 80.0)
    return round(score, 2)


async def _make_plate_candidates(mod: Any, scene: str, aspect: str, user_photo: bytes, debug: dict[str, Any]) -> list[dict[str, Any]]:
    lighting = _lighting_hint(user_photo)
    candidates: list[dict[str, Any]] = []
    jobs: list[tuple[str, str, Callable[[], Awaitable[bytes]]]] = []

    if v139.selfie.previous._gemini_key(mod) and _flag("CELEBRITY_V142_GEMINI_SCENE_ENABLED", True):
        models = v139.selfie.previous._gemini_models(mod)
        count = _integer("CELEBRITY_V142_GEMINI_PLATES", 2, 0, 4)
        for index in range(count):
            model = models[index % len(models)] if models else "gemini-3-pro-image"
            prompt = _scene_prompt(scene, aspect, index, lighting)
            jobs.append((
                f"v142_plate_gemini_{index + 1}",
                f"gemini:{model}",
                lambda model=model, prompt=prompt: v140._gemini_scene_direct(mod, model, prompt, aspect),
            ))

    if v139.selfie._openai_key(mod) and _flag("CELEBRITY_V142_OPENAI_SCENE_ENABLED", True):
        prompt = _scene_prompt(scene, aspect, 2, lighting)
        jobs.append((
            "v142_plate_openai_1",
            "openai:official-images",
            lambda prompt=prompt: v140._openai_scene_direct(mod, prompt, aspect),
        ))

    if v139.selfie._bfl_key() and _flag("CELEBRITY_V142_FLUX_SCENE_ENABLED", True):
        prompt = _scene_prompt(scene, aspect, 1, lighting)
        jobs.append((
            "v142_plate_flux_1",
            f"bfl:{os.environ.get('CELEBRITY_FLUX_MODEL') or 'flux-2-pro'}",
            lambda prompt=prompt: v139.selfie._flux_edit(prompt, [], aspect),
        ))

    semaphore = asyncio.Semaphore(_integer("CELEBRITY_V142_SCENE_PARALLEL", 2, 1, 3))

    async def run_job(name: str, provider: str, factory: Callable[[], Awaitable[bytes]]) -> None:
        async with semaphore:
            stage = v139._stage_start(debug, name, provider)
            try:
                raw = await factory()
                problem = _plate_problem(raw, name)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                score = _plate_score(raw)
                row = {"label": name, "provider": provider, "score": score, "output": raw}
                candidates.append(row)
                debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
                v139._stage_finish(stage, "ok", score=score, bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)

    if jobs:
        await asyncio.gather(*(run_job(*job) for job in jobs))
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


async def _piapi_celebrity(mod: Any, target: bytes, reference: bytes) -> bytes:
    source = v139._face_crop(reference, 1152)
    target = v139._jpeg(target, max_side=2200, quality=96)
    output = await v139.pi_identity._piapi_task(
        mod,
        "multi-face-swap",
        {
            "swap_image": base64.b64encode(source).decode("ascii"),
            "target_image": base64.b64encode(target).decode("ascii"),
            "swap_faces_index": "0",
            "target_faces_index": "0",
        },
    )
    return v139._jpeg(output)


async def _single_face_identity_score(mod: Any, output: bytes, reference: bytes) -> dict[str, Any]:
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision) or not _flag("CELEBRITY_V142_VISION_QC", True):
        return {"score": 55.0, "unknown": True, "reason": "vision-qc-unavailable"}
    ref = ImageOps.fit(_open_rgb(v139._face_crop(reference, 640)), (640, 640), method=Image.Resampling.LANCZOS)
    candidate = ImageOps.fit(_open_rgb(output), (900, 640), method=Image.Resampling.LANCZOS)
    board = v139._encode_board([ref, candidate], height=640)
    prompt = (
        "Quality-control board: LEFT panel is one identity reference; RIGHT panel is a generated photograph containing one "
        "foreground adult on the RIGHT side. Do not identify or name anyone. Compare the reference only to that single visible "
        "foreground face. Return strict JSON only: similarity integer 0-100, exactly_one_main_face boolean, target_face_visible "
        "boolean, reason short string. Allow lighting, expression and lens changes but penalize changed head shape, hairline, eye "
        "spacing, nose, lips and jaw."
    )
    try:
        answer = await vision(prompt, base64.b64encode(board).decode("ascii"), "image/jpeg")
        data = v139._json_object(answer) or {}
        score = max(0.0, min(100.0, float(data.get("similarity") or 0)))
        if data.get("target_face_visible") is False:
            score = 0.0
        if score <= 0:
            return {"score": 55.0, "unknown": True, "reason": str(data.get("reason") or "vision score missing")[:300]}
        return {"score": round(score, 1), "unknown": False, "reason": str(data.get("reason") or "ok")[:300]}
    except Exception as exc:
        return {"score": 55.0, "unknown": True, "reason": f"vision-qc-error:{v139._safe_error(exc)}"[:300]}


async def _celebrity_variants(
    mod: Any,
    plate: dict[str, Any],
    references: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    providers = [item.strip().casefold() for item in str(os.environ.get("CELEBRITY_V142_CELEBRITY_PROVIDERS") or "openai,piapi").split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    for provider in providers:
        if provider == "openai" and not v139.selfie._openai_key(mod):
            continue
        if provider == "piapi" and not v139.pi_identity._piapi_key(mod):
            continue
        label = f"{plate['label']}_celebrity_{provider}"
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
                raw = await _piapi_celebrity(mod, plate["output"], references[0])
            else:
                continue
            problem = _plate_problem(raw, label)
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            qc = await _single_face_identity_score(mod, raw, references[0])
            score = float(qc.get("score") or 0)
            row = {
                "label": label,
                "scene": plate["label"],
                "scene_provider": plate["provider"],
                "celebrity_provider": provider,
                "celebrity_identity": round(score, 1),
                "identity_unknown": bool(qc.get("unknown")),
                "reason": qc.get("reason"),
                "output": raw,
            }
            results.append(row)
            debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
            v139._stage_finish(stage, "ok", score=round(score, 1), unknown=bool(qc.get("unknown")), bytes=len(raw))
            if score >= _number("CELEBRITY_V142_CELEBRITY_STOP_SCORE", 78.0, 50.0, 96.0) and not qc.get("unknown"):
                break
        except Exception as exc:
            v139._record_error(debug, stage, exc)
    results.sort(key=lambda item: (not bool(item.get("identity_unknown")), float(item.get("celebrity_identity") or 0)), reverse=True)
    return results


def _opaque_mean(image: Image.Image, alpha: Image.Image) -> tuple[float, float, float]:
    rgb = image.convert("RGB")
    mask = alpha.point(lambda value: 255 if value >= 32 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return (128.0, 128.0, 128.0)
    rgb = rgb.crop(bbox)
    mask = mask.crop(bbox)
    stat = ImageStat.Stat(rgb, mask=mask)
    return tuple(float(value) for value in stat.mean[:3])


def _harmonise_cutout(cutout: Image.Image, scene_region: Image.Image, face_box: dict[str, float] | None) -> Image.Image:
    original = cutout.convert("RGBA")
    alpha = original.getchannel("A")
    subject_mean = _opaque_mean(original, alpha)
    scene_mean = tuple(float(value) for value in ImageStat.Stat(scene_region.convert("RGB")).mean[:3])
    subject_lum = max(1.0, sum(subject_mean) / 3.0)
    scene_lum = max(1.0, sum(scene_mean) / 3.0)
    factor = max(
        _number("CELEBRITY_V142_MIN_EXPOSURE_MATCH", 0.88, 0.70, 1.0),
        min(_number("CELEBRITY_V142_MAX_EXPOSURE_MATCH", 1.12, 1.0, 1.35), scene_lum / subject_lum),
    )
    adjusted_rgb = ImageEnhance.Brightness(original.convert("RGB")).enhance(factor)
    adjusted_rgb = ImageEnhance.Color(adjusted_rgb).enhance(_number("CELEBRITY_V142_COLOR_MATCH", 0.96, 0.75, 1.15))
    adjusted = adjusted_rgb.convert("RGBA")
    adjusted.putalpha(alpha)

    if face_box:
        scale_x = original.width / max(1.0, float(face_box.get("source_width") or original.width))
        scale_y = original.height / max(1.0, float(face_box.get("source_height") or original.height))
        x = int(float(face_box.get("x") or 0) * scale_x)
        y = int(float(face_box.get("y") or 0) * scale_y)
        w = int(float(face_box.get("w") or 1) * scale_x)
        h = int(float(face_box.get("h") or 1) * scale_y)
        mask = Image.new("L", original.size, 0)
        ImageDraw.Draw(mask).ellipse((max(0, x - w // 3), max(0, y - h // 3), min(original.width, x + w + w // 3), min(original.height, y + h + h // 2)), fill=238)
        mask = mask.filter(ImageFilter.GaussianBlur(max(5.0, min(original.size) * 0.018)))
        adjusted = Image.composite(original, adjusted, mask)
        adjusted.putalpha(alpha)
    return adjusted


def _resize_cutout(info: dict[str, Any], canvas_size: tuple[int, int], face_fraction: float) -> tuple[Image.Image, dict[str, float]]:
    cutout: Image.Image = info["image"]
    face = dict(info.get("face") or {})
    width, height = canvas_size
    if face:
        face_h = max(1.0, float(face.get("h") or 1))
        scale = (height * face_fraction) / face_h
    else:
        scale = min((height * 0.88) / max(1, cutout.height), (width * 0.56) / max(1, cutout.width))
    scale = min(scale, (height * 0.92) / max(1, cutout.height), (width * 0.62) / max(1, cutout.width))
    scale = max(0.25, scale)
    new_size = (max(1, int(cutout.width * scale)), max(1, int(cutout.height * scale)))
    resized = cutout.resize(new_size, Image.Resampling.LANCZOS)
    if face:
        face = {
            "x": float(face.get("x") or 0) * scale,
            "y": float(face.get("y") or 0) * scale,
            "w": float(face.get("w") or 1) * scale,
            "h": float(face.get("h") or 1) * scale,
            "source_width": float(new_size[0]),
            "source_height": float(new_size[1]),
        }
    return resized, face


def _composite_user(scene_raw: bytes, cutout_info: dict[str, Any], variant: int) -> tuple[bytes, dict[str, Any]]:
    scene = _open_rgb(scene_raw)
    width, height = scene.size
    face_fraction = _number("CELEBRITY_V142_USER_FACE_HEIGHT", 0.285, 0.18, 0.38)
    resized, face = _resize_cutout(cutout_info, scene.size, face_fraction)

    targets = (
        (0.265, 0.315),
        (0.235, 0.345),
        (0.285, 0.355),
    )
    target_x, target_y = targets[variant % len(targets)]
    if face:
        face_cx = float(face.get("x") or 0) + float(face.get("w") or 0) / 2.0
        face_cy = float(face.get("y") or 0) + float(face.get("h") or 0) / 2.0
    else:
        face_cx = resized.width * 0.5
        face_cy = resized.height * 0.24
    x = int(width * target_x - face_cx)
    y = int(height * target_y - face_cy)
    x = max(-int(width * 0.08), min(x, int(width * 0.50) - resized.width))
    y = max(-int(height * 0.06), min(y, height - int(resized.height * 0.60)))

    region_box = (max(0, x), max(0, y), min(width, x + resized.width), min(height, y + resized.height))
    region = scene.crop(region_box)
    if region.size != resized.size:
        region = ImageOps.fit(region, resized.size, method=Image.Resampling.LANCZOS)
    resized = _harmonise_cutout(resized, region, face)

    alpha = resized.getchannel("A")
    feather = _number("CELEBRITY_V142_EDGE_FEATHER_PX", 1.15, 0.0, 4.0)
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    resized.putalpha(alpha)

    canvas = scene.convert("RGBA")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(_number("CELEBRITY_V142_SHADOW_BLUR", 14.0, 3.0, 35.0)))
    shadow_alpha = shadow_alpha.point(lambda value: int(value * _number("CELEBRITY_V142_SHADOW_OPACITY", 0.22, 0.0, 0.55)))
    shadow = Image.new("RGBA", resized.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    shadow_offset = (_integer("CELEBRITY_V142_SHADOW_X", 5, -20, 20), _integer("CELEBRITY_V142_SHADOW_Y", 8, -20, 30))
    canvas.alpha_composite(shadow, (x + shadow_offset[0], y + shadow_offset[1]))
    canvas.alpha_composite(resized, (x, y))

    metadata = {
        "cutout_provider": cutout_info.get("provider"),
        "cutout_label": cutout_info.get("label"),
        "placement_variant": variant,
        "position": [x, y],
        "size": [resized.width, resized.height],
        "user_pixel_policy": "source_pixels_preserved_no_generation",
        "face_geometry_lock": True,
    }
    return _encode_jpeg(canvas), metadata


def _final_layout_problem(raw: bytes) -> str:
    problem = v140._soft_scene_problem(raw, "v142-final")
    if problem:
        return problem
    image = _open_rgb(raw)
    boxes = sorted(_face_boxes(raw), key=lambda item: float(item.get("x") or 0))
    if len(boxes) >= 2:
        left, right = boxes[0], boxes[-1]
        left_cx = (float(left.get("x") or 0) + float(left.get("w") or 0) / 2.0) / max(1, image.width)
        right_cx = (float(right.get("x") or 0) + float(right.get("w") or 0) / 2.0) / max(1, image.width)
        if left_cx >= right_cx or left_cx > 0.58 or right_cx < 0.42:
            return "final face layout is not left-user/right-celebrity"
        left_area = max(1.0, float(left.get("w") or 1) * float(left.get("h") or 1))
        right_area = max(1.0, float(right.get("w") or 1) * float(right.get("h") or 1))
        ratio = left_area / right_area
        if ratio < 0.25 or ratio > 4.0:
            return "final foreground face scales are incompatible"
    return ""


async def _build_composite_candidates(
    mod: Any,
    celebrity_variant: dict[str, Any],
    cutouts: list[dict[str, Any]],
    user_ref: bytes,
    celebrity_ref: bytes,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    placements = _integer("CELEBRITY_V142_PLACEMENT_VARIANTS", 2, 1, 3)
    for cutout in cutouts:
        for variant in range(placements):
            label = f"{celebrity_variant['label']}_{cutout['label']}_composite_{variant + 1}"
            stage = v139._stage_start(debug, label, "local-composite")
            try:
                raw, placement = _composite_user(celebrity_variant["output"], cutout, variant)
                problem = _final_layout_problem(raw)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                qc = await v139._final_identity_qc(mod, raw, user_ref, celebrity_ref)
                user_score = max(float(qc.get("user") or 0), _number("CELEBRITY_V142_PRESERVED_USER_SCORE_FLOOR", 94.0, 75.0, 100.0))
                celebrity_score = float(qc.get("celebrity") or celebrity_variant.get("celebrity_identity") or 0)
                minimum = min(user_score, celebrity_score)
                weighted = user_score * 0.58 + celebrity_score * 0.42
                structural = v139._structural_score(raw)
                artifact = v141._artifact_metrics(raw)
                total = user_score * 0.28 + celebrity_score * 0.38 + structural * 0.14 + float(artifact.get("quality") or 0) * 0.20
                row = {
                    "label": label,
                    "scene": celebrity_variant.get("scene"),
                    "scene_provider": celebrity_variant.get("scene_provider"),
                    "user_provider": f"cutout:{cutout.get('provider')}",
                    "celebrity_provider": celebrity_variant.get("celebrity_provider"),
                    "user_identity": round(user_score, 1),
                    "celebrity_identity": round(celebrity_score, 1),
                    "identity_min": round(minimum, 1),
                    "identity_weighted": round(weighted, 1),
                    "identity_unknown": bool(qc.get("unknown")) and bool(celebrity_variant.get("identity_unknown")),
                    "structural": round(structural, 1),
                    "artifact_quality": float(artifact.get("quality") or 0),
                    "total": round(total, 2),
                    "reason": str(qc.get("reason") or celebrity_variant.get("reason") or "ok")[:400],
                    "user_pixel_preserved": True,
                    "user_face_regenerated": False,
                    "placement": placement,
                    "output": raw,
                }
                rows.append(row)
                debug.setdefault("composite_candidates", []).append({key: value for key, value in row.items() if key != "output"})
                v139._stage_finish(stage, "ok", total=row["total"], user=row["user_identity"], celebrity=row["celebrity_identity"], bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    rows.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
    return rows


async def _run_v142_generation(
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
        "architecture": "right_scene_plate+celebrity_identity+source_user_cutout+local_harmonisation",
        "user_generation": "disabled",
        "user_pixel_lock": "source_pixels_first",
        "nano_banana_comet": "disabled",
        "cutouts": [],
        "composite_candidates": [],
        "legacy_fallback": None,
    })
    user_refs = [user_photo, *[raw for raw in (additional_user_refs or []) if raw]]
    best_public_ref = await v139.selfie.impl._best_reference(celebrity_refs)
    public_refs = [best_public_ref, *[raw for raw in celebrity_refs if raw is not best_public_ref]]

    try:
        cutouts: list[dict[str, Any]] = []
        cutout_limit = _integer("CELEBRITY_V142_USER_CUTOUTS", 2, 1, 2)
        for index, user_ref in enumerate(user_refs[:cutout_limit], start=1):
            try:
                cutouts.append(await _prepare_user_cutout(mod, user_ref, debug, f"user{index}"))
            except Exception as exc:
                debug["errors"].append({"stage": f"cutout_user{index}", "provider": "cutout", "category": v139._classify_error(exc), "error": v139._safe_error(exc)})
        if not cutouts:
            raise v139.PipelineError("user_cutout", "No usable user cutout was produced", debug=debug)

        plates = await _make_plate_candidates(mod, scene, aspect, user_photo, debug)
        if not plates:
            raise v139.PipelineError("scene_generation", "No right-side scene plate was produced", debug=debug)

        finals: list[dict[str, Any]] = []
        plate_limit = _integer("CELEBRITY_V142_PLATES_TO_IDENTITY", 2, 1, 3)
        for plate in plates[:plate_limit]:
            celebrities = await _celebrity_variants(mod, plate, public_refs, celebrity_name, aspect, debug)
            for celebrity_variant in celebrities[:2]:
                finals.extend(await _build_composite_candidates(mod, celebrity_variant, cutouts, user_photo, best_public_ref, debug))

        if not finals:
            raise v139.PipelineError("composite_pipeline", "No source-pixel-preserving composite survived structural checks", debug=debug)

        best = finals[0]
        debug["selected"] = {key: value for key, value in best.items() if key != "output"}
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        debug["failure_class"] = None
        public = v139._public_debug(debug)
        public["cutouts"] = debug.get("cutouts", [])[-4:]
        public["composite_candidates"] = debug.get("composite_candidates", [])[-8:]
        public["legacy_fallback"] = debug.get("legacy_fallback")
        _LAST_RUN_DEBUG = public
        v139._LAST_RUN_DEBUG = public
        return best["output"], public
    except Exception as exc:
        if _flag("CELEBRITY_V142_LEGACY_FALLBACK", True):
            stage = v139._stage_start(debug, "v142_legacy_fallback", "v140")
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
                debug["legacy_fallback"] = "used"
                debug["selected"] = dict(fallback_debug.get("selected") or {})
                debug["selected"]["user_pixel_preserved"] = False
                debug["selected"]["user_face_regenerated"] = True
                debug["selected"]["pipeline"] = "v140-legacy-fallback"
                v139._stage_finish(stage, "ok", bytes=len(output))
                debug["finished_at"] = time.time()
                debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
                debug["failure_class"] = None
                public = v139._public_debug(debug)
                public["cutouts"] = debug.get("cutouts", [])[-4:]
                public["composite_candidates"] = debug.get("composite_candidates", [])[-8:]
                public["legacy_fallback"] = "used"
                _LAST_RUN_DEBUG = public
                v139._LAST_RUN_DEBUG = public
                return output, public
            except Exception as fallback_exc:
                v139._record_error(debug, stage, fallback_exc)
        category = getattr(exc, "category", None) or v139._classify_error(exc)
        debug["failure_class"] = category
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        public = v139._public_debug(debug)
        public["cutouts"] = debug.get("cutouts", [])[-4:]
        public["composite_candidates"] = debug.get("composite_candidates", [])[-8:]
        public["legacy_fallback"] = debug.get("legacy_fallback")
        _LAST_RUN_DEBUG = public
        v139._LAST_RUN_DEBUG = public
        if isinstance(exc, v139.PipelineError):
            exc.debug = public
            raise
        raise v139.PipelineError(category, v139._safe_error(exc), debug=public) from exc


def _result_kb(has_selected: bool):
    from telegram import InlineKeyboardMarkup

    base = _ORIGINAL_V141_RESULT_KB(has_selected)
    rows = [
        [ui138._inline_button("Улучшить только лицо знаменитости", "cs142:celebrity", primary=True)],
        [ui138._inline_button("Убрать рябь / улучшить качество", "cs141:quality")],
        [ui138._inline_button("Пересобрать только знаменитость", "cs142:celebrity_rebuild")],
        [ui138._inline_button("Вернуть предыдущий результат", "cs141:undo")],
    ]
    blocked = (
        "улучшить сходств",
        "усилить мое лицо",
        "усилить моё лицо",
        "усилить лицо знаменит",
        "убрать ряб",
        "вернуть предыдущ",
    )
    for row in getattr(base, "inline_keyboard", None) or []:
        filtered = []
        for button in row:
            text = " ".join(str(getattr(button, "text", "") or "").casefold().replace("ё", "е").split())
            if any(marker.replace("ё", "е") in text for marker in blocked):
                continue
            filtered.append(button)
        if filtered:
            rows.append(filtered)
    return InlineKeyboardMarkup(rows)


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    if refinement:
        await v141._postprocess(update, context, "celebrity")
        return

    engine = v139.selfie.engine
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Откройте режим заново.")
        return
    now = time.monotonic()
    if str(session.get("state") or "") in {"queued", "generating", "refining_v141"} and now - float(session.get("generation_started_monotonic") or 0) < 1800:
        await update.effective_message.reply_text("⏳ Эта генерация уже выполняется. Дождитесь результата.")
        return

    user_photo = engine._read_path(session.get("user_photo_path"))
    second_user = engine._read_path(session.get("user_photo_2_path"))
    refs = [raw for raw in (engine._read_path(path) for path in engine._reference_paths(session)) if raw]
    scene = str(session.get("scene") or "").strip()
    celebrity_name = str(session.get("celebrity_name") or session.get("selected_celebrity_name") or "выбранный человек").strip()
    if not user_photo:
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text("Пришлите своё чёткое селфи ещё раз.")
        return
    if not refs:
        session["state"] = "await_custom_refs"
        await update.effective_message.reply_text("Загрузите 1–4 чётких фото выбранной персоны.")
        return
    if not scene:
        session["state"] = "await_scene"
        await update.effective_message.reply_text("Выберите или опишите сцену.", reply_markup=engine._scene_kb())
        return
    mod = engine._runtime_module()
    if mod is None:
        await update.effective_message.reply_text("Сервис ещё загружается. Повторите через несколько секунд.")
        return

    generation_id = uuid.uuid4().hex
    session.update({
        "generation_id": generation_id,
        "generation_started_monotonic": now,
        "generation_scene_snapshot": scene,
        "generation_celebrity_snapshot": celebrity_name,
        "state": "queued",
    })

    async def work() -> bool:
        if not v139.selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            return False
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Создаю сцену и выбранного человека отдельно. Ваше лицо и внешность не перерисовываются: "
            "я вырежу вас из исходного селфи и встрою исходные пиксели в готовую сцену. Обычно это занимает 3–8 минут."
        )
        try:
            output, debug = await _run_v142_generation(
                mod,
                user_photo,
                refs,
                celebrity_name,
                scene,
                additional_user_refs=[second_user] if second_user else [],
            )
        except Exception as exc:
            debug = getattr(exc, "debug", None) or _LAST_RUN_DEBUG or {}
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "await_scene"
                session["v139_debug"] = debug if isinstance(debug, dict) else {}
                session["v142_debug"] = debug if isinstance(debug, dict) else {}
                session["last_generation_error"] = v139._safe_error(exc)
                session["last_generation_failed_at"] = time.time()
                session["generation_failures"] = int(session.get("generation_failures") or 0) + 1
                session.pop("generation_id", None)
                run_id = str((debug or {}).get("run_id") or "-")
                await update.effective_message.reply_text(
                    "❌ Генерация остановлена. " + v139._failure_message(exc, debug or {}) +
                    f"\nКод диагностики: {run_id}. Кредиты за невыданный результат не должны списываться.",
                    reply_markup=v139.selfie.v133._failure_kb(),
                )
            return False

        if not v139.selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            if str(session.get("generation_id") or "") == generation_id:
                session.pop("generation_id", None)
            return False

        selected = debug.get("selected") or {}
        delivery_mode, identity_min = v139._delivery_state(selected)
        session["v139_debug"] = debug
        session["v142_debug"] = debug
        session["delivery_mode"] = delivery_mode
        session["delivery_identity_min"] = identity_min
        session["result_path"] = engine._store_image(session, "result_v142.jpg", output)
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session["generation_failures"] = 0
        session.pop("generation_id", None)
        v141._snapshot_accepted(session)

        from telegram import InputFile

        bio = BytesIO(output)
        bio.name = "celebrity_selfie.jpg"
        preserved = bool(selected.get("user_pixel_preserved"))
        if delivery_mode == "verified":
            title = "📸 AI-селфи готово ✅"
            quality = f"Минимальная оценка двух лиц {identity_min:.0f}/100."
        else:
            title = "📸 Предварительный AI-результат"
            quality = f"Минимальная оценка двух лиц {identity_min:.0f}/100; результат показан для визуальной оценки."
        if preserved:
            architecture = "Ваш образ вставлен из исходного селфи без генерации лица; нейросеть создала сцену и вторую персону."
        else:
            architecture = "Сработал резервный генеративный маршрут; это отмечено в диагностике."
        caption = (
            f"{title}\n"
            f"Персона: {celebrity_name}\n"
            f"{architecture}\n"
            f"{quality}\n"
            "Пометка: изображение создано ИИ и не подтверждает реальную встречу, поддержку или партнёрство."
        )
        markup = engine._result_kb(bool(engine._selected_entry(session)))
        if engine._flag("CELEBRITY_SELFIE_SEND_AS_DOCUMENT", True):
            await update.effective_message.reply_document(InputFile(bio), caption=caption[:1024], reply_markup=markup)
        else:
            await update.effective_message.reply_photo(photo=output, caption=caption[:1024], reply_markup=markup)
        return True

    pay = getattr(mod, "_try_pay_then_do", None)
    if not callable(pay):
        await work()
        return
    cost = float(os.environ.get("CELEBRITY_V142_UNIT_COST_USD") or os.environ.get("CELEBRITY_V139_UNIT_COST_USD") or 0.80)
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind="celebrity_selfie_v142",
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "generation_id": generation_id,
            "pipeline": VERSION,
            "architecture": "scene+celebrity+source-user-cutout",
            "user_face_regeneration": False,
            "nano_banana_comet": False,
            "aspect": v139.selfie._aspect_for_scene(scene),
            "user_references": 2 if second_user else 1,
        },
    )


async def _callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(getattr(query, "data", "") or "")
    if data in {"cs142:celebrity", "cs142:celebrity_rebuild", "cs141:similarity"}:
        with contextlib.suppress(Exception):
            await query.answer()
        await v141._postprocess(update, context, "celebrity")
        raise ApplicationHandlerStop
    if data == "cs141:user":
        with contextlib.suppress(Exception):
            await query.answer()
        await update.effective_message.reply_text(
            "🛡 Ваше лицо уже сохранено из исходного селфи без генерации геометрии. Чтобы изменить именно ваш ракурс, "
            "создайте новое AI-селфи с другим исходным фото; текущий кадр не будет перерисовывать ваше лицо."
        )
        raise ApplicationHandlerStop


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or _LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    mod = v139.selfie.engine._runtime_module()
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=right_scene_plate+celebrity_identity+source_user_cutout+local_harmonisation",
        "user_face_generation=disabled",
        "user_pixel_lock=source_pixels_first",
        "user_face_geometry_lock=required",
        "nano_banana_comet=disabled",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"photoroom={'ready' if (mod is not None and bool(_photoroom_key(mod))) else 'missing'}",
        f"local_rembg={'enabled' if _flag('CELEBRITY_V142_LOCAL_REMBG_FALLBACK', True) else 'disabled'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"cutouts={str(debug.get('cutouts') or '-')[:1000]}",
        f"legacy_fallback={debug.get('legacy_fallback') or '-'}",
        f"delivery_mode={session.get('delivery_mode') or '-'}",
        f"selected={str(selected or '-')[:1400]}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    stages = debug.get("stages") or []
    if stages:
        lines.append("stages:")
        for stage in stages[-12:]:
            lines.append(
                f"- {stage.get('name')} [{stage.get('provider')}] {stage.get('status')} "
                f"{stage.get('duration_s', '-')}s score={stage.get('score', stage.get('total', '-'))} "
                f"error={str(stage.get('error') or '')[:180]}"
            )
    errors = debug.get("errors") or []
    if errors:
        lines.append("errors:")
        for item in errors[-6:]:
            lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:260]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    os.environ.setdefault("CELEBRITY_V142_UNIT_COST_USD", "0.80")
    os.environ.setdefault("CELEBRITY_V142_CUTOUT_PROVIDERS", "photoroom,rembg")
    os.environ.setdefault("CELEBRITY_V142_LOCAL_REMBG_FALLBACK", "1")
    os.environ.setdefault("CELEBRITY_V142_PHOTOROOM_SIZE", "full")
    os.environ.setdefault("CELEBRITY_V142_USER_CUTOUTS", "2")
    os.environ.setdefault("CELEBRITY_V142_GEMINI_PLATES", "2")
    os.environ.setdefault("CELEBRITY_V142_PLATES_TO_IDENTITY", "2")
    os.environ.setdefault("CELEBRITY_V142_CELEBRITY_PROVIDERS", "openai,piapi")
    os.environ.setdefault("CELEBRITY_V142_PLACEMENT_VARIANTS", "2")
    os.environ.setdefault("CELEBRITY_V142_PRESERVED_USER_SCORE_FLOOR", "94")
    os.environ.setdefault("CELEBRITY_V142_LEGACY_FALLBACK", "1")
    # OpenAI quality cleanup can redraw a preserved user. Keep v141's local
    # deterministic denoise, but disable generative whole-image cleanup by default.
    os.environ["CELEBRITY_V141_OPENAI_QUALITY_CLEANUP"] = str(os.environ.get("CELEBRITY_V142_ALLOW_GENERATIVE_CLEANUP") or "0")

    v139.VERSION = VERSION
    v139._run_two_stage_generation = _run_v142_generation
    v139._generate = _generate
    v139.selfie._run_v142_generation = _run_v142_generation
    v139.selfie._generate = _generate
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._generate = _generate
    v139.selfie.engine._result_kb = _result_kb
    v139.selfie.engine._diag = _diag
    v141._generate = _generate
    v141._result_kb = _result_kb


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
    output, _ = await _run_v142_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(CallbackQueryHandler(_callback), group=_GROUP)
            for command in (
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
    "_run_v142_generation",
    "_prepare_user_cutout",
    "_photoroom_cutout",
    "_local_rembg_cutout",
    "_scene_prompt",
    "_composite_user",
    "_result_kb",
    "_generate",
    "_diag",
]
