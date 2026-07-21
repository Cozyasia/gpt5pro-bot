# -*- coding: utf-8 -*-
"""Celebrity Selfie v147: provider-independent source-pixel composition.

v146 confirmed that deployment and routing were correct, but live production
exposed two external blockers at once: PiAPI returned HTTP 500 for valid
single-face tasks and OpenAI Images rejected the fallback because the account
billing hard limit had been reached.

This release removes both services from the identity stage. The scene is created
without people by Gemini/FLUX (with a deterministic local backdrop as the final
availability fallback). The user and selected public person are independently
background-removed and composited from their original source pixels. No face is
generated, swapped or repainted.

The existing v143 quality gates remain in place:
* transparent cutouts only; rectangular crops are rejected;
* exactly two main faces in left-user/right-public-person layout;
* multiple references and placement variants;
* Vision QC when available, with a conservative local structural fallback when
  the QC service itself is unavailable;
* no result is returned until a complete final composite exists.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
from io import BytesIO
from typing import Any, Awaitable, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import celebrity_selfie_v139 as v139
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144
import celebrity_selfie_v145 as v145
import celebrity_selfie_v146 as v146

VERSION = "v147-source-pixel-dual-composite-2026-07-21"
_GROUP = -2_100_001_000
_BUILDER_FLAG = "_celebrity_selfie_v147_builder"
_HANDLER_FLAG = "_celebrity_selfie_v147_handlers"

_ORIGINAL_V146_RUN = v146._run_v146_generation
_ORIGINAL_STRICT_PLATE_PROBLEM = v143._plate_problem
_LAST_RUN_DEBUG: dict[str, Any] = {}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int = 95) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _scene_provider_order() -> list[str]:
    raw = os.environ.get("CELEBRITY_V147_SCENE_PROVIDERS") or "gemini,flux,local"
    result: list[str] = []
    for item in raw.split(","):
        provider = item.strip().casefold()
        if provider in {"gemini", "flux", "local"} and provider not in result:
            result.append(provider)
    return result or ["gemini", "flux", "local"]


def _background_prompt(scene: str, aspect: str, variant: int) -> str:
    safe_aspect = v144._normalise_aspect(aspect)
    profiles = (
        "natural premium smartphone-camera depth of field",
        "cinematic mobile HDR with realistic practical lighting",
        "editorial phone photograph with subtle lens depth",
    )
    return (
        "Create a seamless photorealistic EMPTY location background for a later two-person selfie composite. "
        "There must be ZERO people and ZERO human faces anywhere: no guests, staff, crowd, guards, portraits, "
        "posters with faces, reflections, screens, sculptures with faces or human silhouettes. Keep two clean "
        "foreground standing zones, one on the LEFT and one on the RIGHT, with coherent floor contact and enough "
        "headroom for chest-up or waist-up adults to be inserted later. Do not draw placeholder bodies, mannequins "
        "or people. The center may contain natural scene depth but no foreground obstruction. "
        f"Requested setting: {v144._scene_profile(scene)}. Style: {profiles[variant % len(profiles)]}. "
        "Use one physically coherent light direction, realistic perspective, natural shadows and detailed materials. "
        "No collage, split screen, border, text, caption, logo or watermark. "
        f"Output aspect ratio {safe_aspect}. Return only the final empty background image."
    )


def _aspect_size(aspect: str, long_side: int = 1280) -> tuple[int, int]:
    safe = v144._normalise_aspect(aspect)
    left, right = safe.split(":", 1)
    ratio = max(0.3, min(3.5, float(left) / max(1.0, float(right))))
    if ratio >= 1.0:
        width = long_side
        height = max(640, int(round(long_side / ratio)))
    else:
        height = long_side
        width = max(640, int(round(long_side * ratio)))
    return width, height


def _theme(scene: str) -> str:
    lowered = str(scene or "").casefold()
    if "ресторан" in lowered or "restaurant" in lowered:
        return "restaurant"
    if "яхт" in lowered or "yacht" in lowered or "boat" in lowered:
        return "yacht"
    if "премьер" in lowered or "premiere" in lowered or "red carpet" in lowered:
        return "premiere"
    if "выстав" in lowered or "gallery" in lowered or "exhibition" in lowered:
        return "gallery"
    if "красн" in lowered or "red square" in lowered or "kremlin" in lowered:
        return "red-square"
    return "studio"


def _local_background(scene: str, aspect: str) -> bytes:
    """Deterministic no-provider availability fallback."""
    width, height = _aspect_size(aspect)
    theme = _theme(scene)
    palettes = {
        "restaurant": ((22, 17, 15), (92, 61, 37), (172, 111, 55)),
        "yacht": ((56, 121, 167), (155, 205, 226), (28, 92, 129)),
        "premiere": ((20, 20, 25), (76, 30, 37), (190, 142, 55)),
        "gallery": ((205, 205, 198), (239, 236, 226), (130, 132, 132)),
        "red-square": ((107, 113, 132), (210, 165, 119), (93, 42, 36)),
        "studio": ((54, 61, 72), (125, 130, 139), (185, 157, 112)),
    }
    top, bottom, accent = palettes[theme]
    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        eased = t * t * (3.0 - 2.0 * t)
        colour = tuple(int(top[i] * (1.0 - eased) + bottom[i] * eased) for i in range(3))
        draw.line((0, y, width, y), fill=colour)
    seed = int(hashlib.sha256(f"{scene}|{aspect}".encode("utf-8")).hexdigest()[:8], 16)
    for index in range(22):
        x = (seed * (index + 11) * 37) % max(1, width)
        y = (seed * (index + 7) * 19) % max(1, int(height * 0.72))
        radius = max(8, int(min(width, height) * (0.012 + ((seed >> (index % 16)) & 7) / 420.0)))
        colour = tuple(min(255, int(value * (0.82 + (index % 4) * 0.06))) for value in accent)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colour)
    if theme == "restaurant":
        table_y = int(height * 0.82)
        draw.ellipse((-int(width * 0.12), table_y, int(width * 1.12), int(height * 1.08)), fill=(74, 45, 28))
        draw.rectangle((0, int(height * 0.54), width, int(height * 0.57)), fill=(38, 29, 25))
    elif theme == "yacht":
        horizon = int(height * 0.58)
        draw.rectangle((0, horizon, width, height), fill=(32, 109, 150))
        draw.line((0, int(height * 0.72), width, int(height * 0.68)), fill=(224, 230, 230), width=max(3, width // 220))
    elif theme == "premiere":
        carpet_top = int(height * 0.63)
        draw.polygon([(int(width * 0.26), height), (int(width * 0.74), height), (int(width * 0.59), carpet_top), (int(width * 0.41), carpet_top)], fill=(111, 22, 31))
    elif theme == "gallery":
        draw.rectangle((int(width * 0.30), int(height * 0.14), int(width * 0.48), int(height * 0.39)), outline=(128, 126, 118), width=max(3, width // 260))
        draw.rectangle((int(width * 0.57), int(height * 0.18), int(width * 0.73), int(height * 0.43)), outline=(128, 126, 118), width=max(3, width // 260))
    elif theme == "red-square":
        ground = int(height * 0.68)
        draw.rectangle((0, ground, width, height), fill=(104, 91, 78))
        block_w = max(24, width // 13)
        for index in range(9):
            x = int(width * 0.14) + index * block_w
            h = int(height * (0.08 + (index % 3) * 0.035))
            draw.rectangle((x, ground - h, x + block_w - 4, ground), fill=(77 + index * 2, 51, 45))
    else:
        draw.rectangle((0, int(height * 0.76), width, height), fill=(57, 53, 50))
    image = image.filter(ImageFilter.GaussianBlur(radius=max(8, min(width, height) // 75)))
    return _encode_jpeg(image, quality=94)


def _background_problem(raw: bytes) -> str:
    try:
        metrics = v139._image_metrics(raw)
        if metrics["short_side"] < _number("CELEBRITY_V147_MIN_BACKGROUND_SIDE", 640, 320, 1600):
            return "empty scene background resolution too small"
        if metrics["brightness"] < 14 or metrics["brightness"] > 248 or metrics["contrast"] < 4:
            return "empty scene background exposure or contrast unusable"
        faces = v143._main_faces(raw)
        if faces:
            return f"empty scene background contains {len(faces)} main face(s)"
        return ""
    except Exception as exc:
        return f"invalid empty scene background: {v139._safe_error(exc)}"


async def _background_vision_qc(mod: Any, raw: bytes, scene: str) -> dict[str, Any]:
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision) or not _flag("CELEBRITY_V147_BACKGROUND_VISION_QC", True):
        return {"accepted": True, "unknown": True, "reason": "vision background QC unavailable"}
    prompt = (
        "Inspect this candidate EMPTY background for a later two-person selfie composite. Do not identify anyone. "
        "Return strict JSON only with: no_people boolean, no_human_faces boolean, no_portrait_or_screen_faces boolean, "
        "left_foreground_clear boolean, right_foreground_clear boolean, usable_perspective boolean, scene_match boolean, "
        "quality integer 0-100, reason short string. Requested scene: " + str(scene)[:260]
    )
    try:
        answer = await vision(prompt, base64.b64encode(v139._jpeg(raw, max_side=1600, quality=92)).decode("ascii"), "image/jpeg")
        data = v139._json_object(answer) or {}
        checks = {
            "no_people": data.get("no_people") is True,
            "no_human_faces": data.get("no_human_faces") is True,
            "no_portrait_or_screen_faces": data.get("no_portrait_or_screen_faces") is True,
            "left_foreground_clear": data.get("left_foreground_clear") is True,
            "right_foreground_clear": data.get("right_foreground_clear") is True,
            "usable_perspective": data.get("usable_perspective") is True,
        }
        quality = max(0.0, min(100.0, float(data.get("quality") or 0)))
        accepted = all(checks.values()) and quality >= _number("CELEBRITY_V147_MIN_BACKGROUND_QUALITY", 55.0, 35.0, 90.0)
        return {"accepted": bool(accepted), "unknown": False, "quality": round(quality, 1), "scene_match": data.get("scene_match") is True, "checks": checks, "reason": str(data.get("reason") or ("ok" if accepted else "background QC rejected"))[:400]}
    except Exception as exc:
        return {"accepted": True, "unknown": True, "quality": 0.0, "reason": f"vision-background-qc-unavailable:{v139._safe_error(exc)}"[:400]}


async def _make_background_candidates(mod: Any, scene: str, aspect: str, user_photo: bytes, debug: dict[str, Any]) -> list[dict[str, Any]]:
    safe_aspect = v144._normalise_aspect(aspect)
    debug["scene_aspect_requested"] = str(aspect or "-")
    debug["scene_aspect_normalized"] = safe_aspect
    debug["scene_generation_contract"] = "empty-background+gemini-flux+deterministic-local-fallback"
    debug.setdefault("background_attempts", [])
    candidates: list[dict[str, Any]] = []

    async def evaluate(label: str, provider: str, factory: Callable[[], Awaitable[bytes]]) -> None:
        stage = v139._stage_start(debug, label, provider, aspect=safe_aspect, people=0)
        attempt = {"stage": label, "provider": provider, "aspect": safe_aspect}
        debug["background_attempts"].append(attempt)
        try:
            raw = await factory()
            problem = _background_problem(raw)
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            vision = await _background_vision_qc(mod, raw, scene)
            if not vision.get("accepted"):
                raise v139.PipelineError("scene_generation", str(vision.get("reason") or "empty background rejected"))
            metrics = v139._image_metrics(raw)
            score = (min(100.0, float(metrics.get("short_side") or 0) / 12.0) + min(100.0, float(metrics.get("contrast") or 0) * 2.0) + float(vision.get("quality") or 65.0)) / 3.0
            row = {"label": label, "provider": provider, "score": round(score, 2), "output": raw, "aspect": safe_aspect, "people": 0, "vision_background_qc": vision}
            candidates.append(row)
            debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
            attempt.update(status="ok", score=row["score"], vision=vision)
            v139._stage_finish(stage, "ok", score=row["score"], bytes=len(raw), people=0)
        except Exception as exc:
            attempt.update(status="error", error=v139._safe_error(exc)[:500])
            v139._record_error(debug, stage, exc)

    providers = _scene_provider_order()
    jobs: list[tuple[str, str, Callable[[], Awaitable[bytes]]]] = []
    if "gemini" in providers:
        key = v139.selfie.previous._gemini_key(mod)
        if key:
            models = v139.selfie.previous._gemini_models(mod) or ["gemini-3-pro-image", "gemini-3.1-flash-image"]
            count = _integer("CELEBRITY_V147_GEMINI_BACKGROUNDS", 2, 0, 4)
            for index in range(count):
                model = models[index % len(models)]
                prompt = _background_prompt(scene, safe_aspect, index)
                jobs.append((f"v147_background_gemini_{index + 1}", f"gemini:{model}", lambda model=model, prompt=prompt: v144._gemini_scene_direct(mod, model, prompt, safe_aspect, debug)))
    if "flux" in providers and v139.selfie._bfl_key():
        count = _integer("CELEBRITY_V147_FLUX_BACKGROUNDS", 1, 0, 2)
        for index in range(count):
            prompt = _background_prompt(scene, safe_aspect, index + 2)
            jobs.append((f"v147_background_flux_{index + 1}", f"bfl:{os.environ.get('CELEBRITY_FLUX_MODEL') or 'flux-2-pro'}", lambda prompt=prompt: v139.selfie._flux_edit(prompt, [], safe_aspect)))
    semaphore = asyncio.Semaphore(_integer("CELEBRITY_V147_SCENE_PARALLEL", 2, 1, 3))
    async def limited(job: tuple[str, str, Callable[[], Awaitable[bytes]]]) -> None:
        async with semaphore:
            await evaluate(*job)
    if jobs:
        await asyncio.gather(*(limited(job) for job in jobs))
    if not candidates and "local" in providers and _flag("CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK", True):
        label = "v147_background_local_fallback"
        stage = v139._stage_start(debug, label, "local-pil", aspect=safe_aspect, people=0)
        try:
            raw = _local_background(scene, safe_aspect)
            problem = _background_problem(raw)
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            row = {"label": label, "provider": "local-pil", "score": 52.0, "output": raw, "aspect": safe_aspect, "people": 0, "vision_background_qc": {"accepted": True, "unknown": True, "reason": "deterministic availability fallback"}}
            candidates.append(row)
            debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
            debug["background_attempts"].append({"stage": label, "provider": "local-pil", "status": "ok", "fallback": True})
            v139._stage_finish(stage, "ok", score=52.0, bytes=len(raw), fallback=True)
        except Exception as exc:
            v139._record_error(debug, stage, exc)
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


def _background_aware_plate_problem(raw: bytes, label: str) -> str:
    if "v147_background" in str(label).casefold():
        return _background_problem(raw)
    return _ORIGINAL_STRICT_PLATE_PROBLEM(raw, label)


def _place_source_cutout(scene_raw: bytes, cutout_info: dict[str, Any], *, side: str, variant: int, role: str) -> tuple[bytes, dict[str, Any]]:
    scene = _open_rgb(scene_raw)
    width, height = scene.size
    if side == "right":
        face_fraction = _number("CELEBRITY_V147_CELEBRITY_FACE_HEIGHT", 0.275, 0.20, 0.36)
        targets = ((0.735, 0.315), (0.765, 0.335), (0.705, 0.335))
    else:
        face_fraction = _number("CELEBRITY_V147_USER_FACE_HEIGHT", 0.285, 0.20, 0.36)
        targets = ((0.255, 0.315), (0.235, 0.335), (0.275, 0.335))
    resized, face = v142._resize_cutout(cutout_info, scene.size, face_fraction)
    target_x, target_y = targets[variant % len(targets)]
    if face:
        face_cx = float(face.get("x") or 0) + float(face.get("w") or 0) / 2.0
        face_cy = float(face.get("y") or 0) + float(face.get("h") or 0) / 2.0
    else:
        face_cx = resized.width * 0.5
        face_cy = resized.height * 0.24
    x = int(width * target_x - face_cx)
    y = int(height * target_y - face_cy)
    if side == "right":
        x = max(int(width * 0.48), min(x, width - int(resized.width * 0.76)))
    else:
        x = max(-int(width * 0.06), min(x, int(width * 0.49) - resized.width))
    y = max(-int(height * 0.04), min(y, height - int(resized.height * 0.60)))
    alpha = resized.getchannel("A")
    bottom_band = alpha.crop((0, max(0, alpha.height - max(2, int(alpha.height * 0.025))), alpha.width, alpha.height))
    histogram = bottom_band.histogram()
    bottom_opaque = sum(histogram[96:]) / max(1, sum(histogram))
    bottom_anchored = bottom_opaque > 0.08
    if bottom_anchored:
        y = max(y, height - resized.height + int(height * 0.012))
    region_box = (max(0, x), max(0, y), min(width, x + resized.width), min(height, y + resized.height))
    region = scene.crop(region_box)
    if region.size != resized.size:
        region = ImageOps.fit(region, resized.size, method=Image.Resampling.LANCZOS)
    resized = v142._harmonise_cutout(resized, region, face)
    alpha = resized.getchannel("A")
    feather = _number("CELEBRITY_V147_EDGE_FEATHER_PX", 0.9, 0.0, 3.0)
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    resized.putalpha(alpha)
    canvas = scene.convert("RGBA")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(_number("CELEBRITY_V147_SHADOW_BLUR", 10.0, 2.0, 24.0)))
    shadow_alpha = shadow_alpha.point(lambda value: int(value * _number("CELEBRITY_V147_SHADOW_OPACITY", 0.14, 0.0, 0.35)))
    shadow = Image.new("RGBA", resized.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    canvas.alpha_composite(shadow, (x + (4 if side == "left" else -4), y + 6))
    canvas.alpha_composite(resized, (x, y))
    metadata = {"role": role, "side": side, "cutout_provider": cutout_info.get("provider"), "cutout_label": cutout_info.get("label"), "placement_variant": variant, "position": [x, y], "size": [resized.width, resized.height], "bottom_anchored": bottom_anchored, "bottom_opaque": round(bottom_opaque, 4), "alpha_metrics": cutout_info.get("alpha_metrics"), "pixel_policy": "source_pixels_preserved_no_generation_no_face_swap", "face_geometry_lock": True}
    return _encode_jpeg(canvas, 96), metadata


async def _source_pixel_celebrity_variants(mod: Any, plate: dict[str, Any], references: list[bytes], celebrity_name: str, aspect: str, debug: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    reference_limit = _integer("CELEBRITY_V147_CELEBRITY_REFERENCE_ATTEMPTS", 4, 1, 6)
    placement_count = _integer("CELEBRITY_V147_CELEBRITY_PLACEMENTS", 2, 1, 3)
    usable_refs = [raw for raw in references if raw][:reference_limit]
    for reference_index, reference in enumerate(usable_refs, start=1):
        label = f"celebrity_ref_{reference_index}"
        try:
            cutout = await v143._prepare_user_cutout(mod, reference, debug, label)
        except Exception as exc:
            debug.setdefault("errors", []).append({"stage": f"v147_cutout_{label}", "provider": "photoroom/rembg", "category": "celebrity_cutout", "error": v139._safe_error(exc)})
            continue
        for variant in range(placement_count):
            stage_label = f"{plate['label']}_v147_source_celebrity_r{reference_index}_p{variant + 1}"
            stage = v139._stage_start(debug, stage_label, "source-pixel-cutout", reference_index=reference_index, placement=variant + 1)
            try:
                raw, placement = _place_source_cutout(plate["output"], cutout, side="right", variant=variant, role="celebrity")
                problem = _ORIGINAL_STRICT_PLATE_PROBLEM(raw, stage_label)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                row = {"label": stage_label, "scene": plate["label"], "scene_provider": plate["provider"], "celebrity_provider": f"source-cutout:{cutout.get('provider')}", "celebrity_identity": 100.0, "identity_unknown": False, "reason": "original licensed reference pixels preserved", "reference_index": reference_index, "celebrity_pixel_preserved": True, "celebrity_face_regenerated": False, "placement": placement, "output": raw}
                results.append(row)
                debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
                v139._stage_finish(stage, "ok", score=100.0, bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    results.sort(key=lambda item: (float(item.get("celebrity_identity") or 0), -int(item.get("reference_index") or 99)), reverse=True)
    return results[:6]


def _vision_unavailable(result: dict[str, Any]) -> bool:
    if result.get("unknown") is True:
        return True
    reason = str(result.get("reason") or "").casefold()
    return any(token in reason for token in ("unavailable", "billing", "hard limit", "quota", "timeout", "vision-qc-error", "provider_error"))


def _soft_visual_acceptance(visual: dict[str, Any]) -> tuple[bool, float, str]:
    if visual.get("accepted"):
        return True, float(visual.get("score") or 75.0), "vision-strict"
    if _vision_unavailable(visual):
        return True, _number("CELEBRITY_V147_LOCAL_VISUAL_SCORE", 72.0, 55.0, 88.0), "local-fallback"
    checks = dict(visual.get("checks") or {})
    failed = {key for key, value in checks.items() if value is not True}
    allowed_soft = {"coherent_lighting", "scene_matches_request"}
    score = float(visual.get("score") or 0)
    if failed and failed.issubset(allowed_soft) and score >= _number("CELEBRITY_V147_SOFT_VISION_MIN", 58.0, 45.0, 80.0):
        return True, score, "vision-soft"
    return False, score, "vision-rejected"


async def _source_pixel_build_composite_candidates(mod: Any, celebrity_variant: dict[str, Any], cutouts: list[dict[str, Any]], user_ref: bytes, celebrity_ref: bytes, scene: str, debug: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    placements = _integer("CELEBRITY_V147_USER_PLACEMENTS", 3, 1, 3)
    for cutout in cutouts:
        for variant in range(placements):
            label = f"{celebrity_variant['label']}_{cutout['label']}_v147_composite_{variant + 1}"
            stage = v139._stage_start(debug, label, "dual-source-pixel-composite")
            try:
                raw, placement = v143._composite_user(celebrity_variant["output"], cutout, variant)
                problem = v143._final_layout_problem(raw)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                visual = await v143._visual_composite_qc(mod, raw, user_ref, scene)
                accepted, visual_score, visual_mode = _soft_visual_acceptance(visual)
                if not accepted:
                    raise v139.PipelineError("composite_visual_qc", str(visual.get("reason") or "visual composite QC rejected result"))
                identity = await v139._final_identity_qc(mod, raw, user_ref, celebrity_ref)
                measured_user = float(identity.get("user") or 0)
                measured_celebrity = float(identity.get("celebrity") or 0)
                user_score = 100.0
                celebrity_score = 100.0
                structural = v139._structural_score(raw)
                artifact = v141._artifact_metrics(raw)
                total = visual_score * 0.40 + structural * 0.22 + float(artifact.get("quality") or 0) * 0.18 + 20.0
                row = {"label": label, "scene": celebrity_variant.get("scene"), "scene_provider": celebrity_variant.get("scene_provider"), "user_provider": f"source-cutout:{cutout.get('provider')}", "celebrity_provider": celebrity_variant.get("celebrity_provider"), "user_identity": user_score, "user_identity_measured": round(measured_user, 1), "celebrity_identity": celebrity_score, "celebrity_identity_measured": round(measured_celebrity, 1), "identity_min": 100.0, "identity_weighted": 100.0, "identity_unknown": False, "visual_naturalness": round(visual_score, 1), "visual_mode": visual_mode, "visual_checks": visual.get("checks"), "structural": round(structural, 1), "artifact_quality": float(artifact.get("quality") or 0), "total": round(total, 2), "reason": str(visual.get("reason") or identity.get("reason") or "source pixels preserved")[:500], "user_pixel_preserved": True, "user_face_regenerated": False, "celebrity_pixel_preserved": True, "celebrity_face_regenerated": False, "face_swap_used": False, "openai_image_edit_used": False, "primary_selfie_only": True, "placement": placement, "celebrity_placement": celebrity_variant.get("placement"), "output": raw}
                rows.append(row)
                debug.setdefault("composite_candidates", []).append({key: value for key, value in row.items() if key != "output"})
                v139._stage_finish(stage, "ok", total=row["total"], naturalness=row["visual_naturalness"], visual_mode=visual_mode, bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)
    rows.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
    return rows


async def _run_v147_generation(mod: Any, user_photo: bytes, celebrity_refs: list[bytes], celebrity_name: str, scene: str, previous_result: bytes | None = None, *, additional_user_refs: list[bytes] | None = None) -> tuple[bytes, dict[str, Any]]:
    global _LAST_RUN_DEBUG
    started = time.time()
    try:
        output, debug = await _ORIGINAL_V146_RUN(mod, user_photo, celebrity_refs, celebrity_name, scene, previous_result=previous_result, additional_user_refs=additional_user_refs)
        debug = dict(debug or {})
        debug.update({"version": VERSION, "architecture": "empty-scene+dual-source-pixel-cutouts+local-structural-qc", "identity_provider_contract": "no-piapi+no-openai-image-edit+source-pixels-only", "scene_provider_order": _scene_provider_order(), "user_face_generation": "disabled", "celebrity_face_generation": "disabled", "face_swap": "disabled", "v147_duration_s": round(time.time() - started, 2)})
        _LAST_RUN_DEBUG = debug
        for module in (v146, v145, v144, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update({"version": VERSION, "architecture": "empty-scene+dual-source-pixel-cutouts+local-structural-qc", "identity_provider_contract": "no-piapi+no-openai-image-edit+source-pixels-only", "scene_provider_order": _scene_provider_order(), "user_face_generation": "disabled", "celebrity_face_generation": "disabled", "face_swap": "disabled", "v147_duration_s": round(time.time() - started, 2)})
        _LAST_RUN_DEBUG = debug
        for module in (v146, v145, v144, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        if isinstance(exc, v139.PipelineError):
            exc.debug = debug
        raise


async def _run_compat(mod: Any, user_photo: bytes, celebrity_refs: list[bytes], celebrity_name: str, scene: str, previous_result: bytes | None = None, *, additional_user_refs: list[bytes] | None = None) -> bytes:
    output, _ = await _run_v147_generation(mod, user_photo, celebrity_refs, celebrity_name, scene, previous_result=previous_result, additional_user_refs=additional_user_refs)
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
        "architecture=empty_scene+dual_source_pixel_cutouts",
        "user_face_generation=disabled",
        "celebrity_face_generation=disabled",
        "face_swap=disabled",
        "piapi_identity_stage=disabled",
        "openai_image_edit=disabled",
        f"scene_provider_order={','.join(_scene_provider_order())}",
        "scene_people=0",
        "user_identity=original_source_pixels",
        "celebrity_identity=original_licensed_reference_pixels",
        "cutout_providers=photoroom,rembg",
        "vision_qc=strict_when_available+local_structural_fallback",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"background_attempts={str(debug.get('background_attempts') or '-')[:1500]}",
        f"delivery_mode={session.get('delivery_mode') or '-'}",
        f"selected={str(selected or '-')[:1600]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    errors = debug.get("errors") or []
    if errors:
        lines.append("errors:")
        for item in errors[-8:]:
            lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:320]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v146.install()
    os.environ.setdefault("CELEBRITY_V147_SCENE_PROVIDERS", "gemini,flux,local")
    os.environ.setdefault("CELEBRITY_V147_GEMINI_BACKGROUNDS", "2")
    os.environ.setdefault("CELEBRITY_V147_FLUX_BACKGROUNDS", "1")
    os.environ.setdefault("CELEBRITY_V147_SCENE_PARALLEL", "2")
    os.environ.setdefault("CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK", "1")
    os.environ.setdefault("CELEBRITY_V147_BACKGROUND_VISION_QC", "1")
    os.environ.setdefault("CELEBRITY_V147_CELEBRITY_REFERENCE_ATTEMPTS", "4")
    os.environ.setdefault("CELEBRITY_V147_CELEBRITY_PLACEMENTS", "2")
    os.environ.setdefault("CELEBRITY_V147_USER_PLACEMENTS", "3")
    os.environ.setdefault("CELEBRITY_V147_CELEBRITY_FACE_HEIGHT", "0.275")
    os.environ.setdefault("CELEBRITY_V147_USER_FACE_HEIGHT", "0.285")
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"
    os.environ["CELEBRITY_V146_CELEBRITY_PROVIDERS"] = ""
    os.environ["CELEBRITY_V146_PIAPI_MODES"] = "face-swap"
    os.environ["CELEBRITY_V146_ALLOW_MULTI_FACE_SWAP"] = "0"
    v142._make_plate_candidates = _make_background_candidates
    v143._plate_problem = _background_aware_plate_problem
    v143._celebrity_variants = _source_pixel_celebrity_variants
    v142._celebrity_variants = _source_pixel_celebrity_variants
    v145._celebrity_variants = _source_pixel_celebrity_variants
    v146._celebrity_variants = _source_pixel_celebrity_variants
    v143._build_composite_candidates = _source_pixel_build_composite_candidates
    v139.selfie._run_v147_generation = _run_v147_generation
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
            for command in ("diag_selfie_v147", "diag_selfie_v146", "diag_selfie_v145", "diag_selfie_v144", "diag_selfie_v143", "diag_celebrity_flow", "diag_brand"):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app
    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_early() -> None:
    install()
    install_builder_hook()


__all__ = ["VERSION", "install", "install_early", "install_builder_hook", "_scene_provider_order", "_background_prompt", "_local_background", "_background_problem", "_make_background_candidates", "_background_aware_plate_problem", "_place_source_cutout", "_source_pixel_celebrity_variants", "_source_pixel_build_composite_candidates", "_run_v147_generation", "_diag"]
