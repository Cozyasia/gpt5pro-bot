# -*- coding: utf-8 -*-
"""Celebrity Selfie v139: scene-first, sequential identity-lock pipeline.

The pipeline deliberately separates composition from identity:

1. Create clean two-person scene drafts without identity references.
2. Lock the user's identity into the LEFT foreground face only.
3. Lock the selected public-person identity into the RIGHT foreground face only.
4. Validate structure and both identities independently; repair only the weaker side.
5. Return the best structurally valid result as verified or labelled preview.

No Nano Banana/Comet route is used. Direct Gemini Images, official OpenAI Images,
optional FLUX, and the already configured PiAPI identity toolkit are the only
providers in this release.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
import uuid
from io import BytesIO
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image, ImageFilter, ImageOps, ImageStat

import celebrity_selfie_v130 as pi_identity
import celebrity_selfie_v136 as selfie
import ui_selfie_v138 as ui138

VERSION = "v139-two-stage-celebrity-selfie-2026-07-20"
_GROUP = -2_100_000_100
_BUILDER_FLAG = "_celebrity_selfie_v139_builder"
_HANDLER_FLAG = "_celebrity_selfie_v139_handlers"
log = logging.getLogger("gpt-bot.celebrity-selfie-v139")

_LAST_RUN_DEBUG: dict[str, Any] = {}


class PipelineError(RuntimeError):
    def __init__(self, category: str, message: str, *, debug: dict[str, Any] | None = None):
        super().__init__(message)
        self.category = category
        self.debug = debug or {}


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


def _runtime_value(mod: Any, name: str, default: str = "") -> str:
    return str(getattr(mod, name, "") or os.environ.get(name) or default).strip()


def _safe_error(exc: BaseException) -> str:
    text = str(exc or type(exc).__name__).replace("\n", " ").strip()
    for marker in ("Bearer ", "x-api-key", "api_key", "apikey", "token="):
        if marker.casefold() in text.casefold():
            text = text.split(marker, 1)[0] + marker + "[redacted]"
    return text[:900]


def _classify_error(exc: BaseException) -> str:
    text = _safe_error(exc).casefold()
    if isinstance(exc, asyncio.TimeoutError) or any(token in text for token in ("timeout", "timed out", "время ожидания", "превысил время")):
        return "timeout"
    if any(token in text for token in ("http 429", " 429", "rate limit", "quota", "resource_exhausted")):
        return "rate_limit"
    if any(token in text for token in ("http 401", "http 403", "unauthor", "forbidden", "отсутствует", "missing key", "api key")):
        return "auth_or_key"
    if any(token in text for token in ("safety", "moderated", "blocked", "policy", "content filter")):
        return "safety_block"
    if any(token in text for token in ("invalid json", "не вернул task_id", "без изображения", "empty image", "malformed")):
        return "malformed_response"
    if any(token in text for token in ("split", "collage", "reference sheet", "одно лицо", "two usable faces", "структур")):
        return "structural_qc"
    if any(token in text for token in ("identity", "сходств", "лицо", "face")):
        return "identity_qc"
    return "provider_error"


def _new_debug(celebrity_name: str, scene: str, aspect: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "run_id": uuid.uuid4().hex[:12],
        "started_at": time.time(),
        "celebrity": celebrity_name,
        "scene": scene[:300],
        "aspect": aspect,
        "architecture": "scene_first+left_identity+right_identity+weak_side_repair",
        "nano_banana_comet": "disabled",
        "stages": [],
        "scene_candidates": [],
        "identity_candidates": [],
        "errors": [],
        "selected": None,
        "failure_class": None,
    }


def _stage_start(debug: dict[str, Any], name: str, provider: str, **meta: Any) -> dict[str, Any]:
    stage = {
        "name": name,
        "provider": provider,
        "status": "running",
        "started": time.monotonic(),
        **{key: value for key, value in meta.items() if value is not None},
    }
    debug["stages"].append(stage)
    return stage


def _stage_finish(stage: dict[str, Any], status: str, **meta: Any) -> None:
    started = float(stage.pop("started", time.monotonic()))
    stage.update({
        "status": status,
        "duration_s": round(max(0.0, time.monotonic() - started), 2),
        **{key: value for key, value in meta.items() if value is not None},
    })


def _record_error(debug: dict[str, Any], stage: dict[str, Any], exc: BaseException) -> None:
    category = _classify_error(exc)
    text = _safe_error(exc)
    _stage_finish(stage, "error", category=category, error=text)
    debug["errors"].append({"stage": stage.get("name"), "provider": stage.get("provider"), "category": category, "error": text})


def _public_debug(debug: dict[str, Any]) -> dict[str, Any]:
    result = dict(debug)
    result["stages"] = [dict(item) for item in debug.get("stages", [])[-30:]]
    result["scene_candidates"] = [dict(item) for item in debug.get("scene_candidates", [])[-10:]]
    result["identity_candidates"] = [dict(item) for item in debug.get("identity_candidates", [])[-12:]]
    result["errors"] = [dict(item) for item in debug.get("errors", [])[-12:]]
    return result


def _jpeg(raw: bytes, max_side: int = 2200, quality: int = 96) -> bytes:
    return selfie.impl._jpeg(raw, max_side=max_side, quality=quality)


def _face_crop(raw: bytes, size: int = 1152) -> bytes:
    return selfie.base._face_crop(raw, size)


def _image_metrics(raw: bytes) -> dict[str, float]:
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        edge = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edge)
        return {
            "width": float(image.width),
            "height": float(image.height),
            "short_side": float(min(image.size)),
            "brightness": float(stat.mean[0]),
            "contrast": float(stat.stddev[0]),
            "sharpness": float(edge_stat.var[0] ** 0.5),
        }


def _structural_problem(raw: bytes, stage: str) -> str:
    try:
        problem = selfie.base._image_problem(raw, stage=stage, require_two_faces=True)
        if problem:
            return str(problem)
        metrics = _image_metrics(raw)
        if metrics["short_side"] < _number("CELEBRITY_V139_MIN_OUTPUT_SIDE", 640, 320, 1600):
            return "output resolution too small"
        if metrics["brightness"] < 18 or metrics["brightness"] > 244:
            return "output exposure is unusable"
        if metrics["contrast"] < 6:
            return "output contrast is unusable"
        return ""
    except Exception as exc:
        return f"invalid image: {_safe_error(exc)}"


def _structural_score(raw: bytes) -> float:
    try:
        metrics = _image_metrics(raw)
        pixels = min(metrics["width"] * metrics["height"], 6_000_000) / 100_000
        exposure = max(0.0, 40.0 - abs(metrics["brightness"] - 128.0) / 4.0)
        return round(pixels + min(metrics["sharpness"], 80.0) + min(metrics["contrast"], 60.0) + exposure, 2)
    except Exception:
        return 0.0


def _scene_prompt(scene: str, aspect: str, variant: int) -> str:
    framings = (
        "arm-length smartphone selfie, both heads and upper torsos large in frame",
        "candid shoulder-to-shoulder phone photograph, equal eye line and natural lens perspective",
        "slightly wider environmental selfie, both foreground faces still large and unobstructed",
    )
    framing = framings[variant % len(framings)]
    return (
        "Create ONE seamless photorealistic smartphone photograph. This is ONLY a clean composition plate for later "
        "identity replacement: do not imitate any supplied or famous person. Exactly TWO distinct anonymous foreground "
        "adults stand together, LEFT and RIGHT. Both faces must be front-facing or gentle three-quarter view, fully visible, "
        "similar size, unobstructed, well lit, and far from the image edges. Keep hairstyles ordinary and avoid hats, glasses, "
        "hands over faces, profile views, extreme expressions, motion blur, microphones or phones covering faces. "
        f"Composition: {framing}. Scene: {selfie.v134._scene_profile(scene)} "
        "Use coherent bodies, realistic hands, one shared light direction, natural skin texture, mobile HDR and subtle sensor "
        "noise. No third foreground person, no duplicate body, no extra face, no poster portrait, no phone-screen portrait, "
        "no collage, split screen, contact sheet, inset, border, text, logo or watermark. Background bystanders, if essential, "
        f"must be tiny and strongly blurred. Aspect ratio {aspect}. Return only the final image."
    )


def _identity_edit_prompt(side: str, identity_label: str, *, repair: bool = False) -> str:
    side_up = side.upper()
    other = "RIGHT" if side == "left" else "LEFT"
    action = "Repair" if repair else "Replace"
    return (
        f"Edit the FIRST image only. {action} ONLY the {side_up} foreground person's face and identity so it matches the "
        f"identity shown in the following reference image(s): {identity_label}. Preserve the complete accepted scene, crop, "
        f"camera, pose, body, clothes, hands, lighting, background and the {other} foreground person pixel-stably. Preserve "
        "the reference person's real head shape, age, skin tone, hairline, hairstyle, eye spacing, nose, lips, jaw, natural "
        "asymmetry and pores. Do not beautify, de-age, blend identities, move the face to the other person or alter the other "
        "person. Keep exactly two distinct foreground adults in one continuous realistic smartphone photograph. No collage, "
        "split screen, reference sheet, text, logo, border or watermark. Return only the edited photograph."
    )


async def _openai_generate(mod: Any, prompt: str, *, aspect: str) -> bytes:
    key = selfie._openai_key(mod)
    if not key:
        raise RuntimeError("OpenAI image key missing")
    base_url = _runtime_value(mod, "IMAGES_BASE_URL", os.environ.get("OPENAI_IMAGE_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = str(os.environ.get("CELEBRITY_OPENAI_IMAGE_MODEL") or getattr(mod, "IMAGES_MODEL", "") or "gpt-image-1")
    timeout_s = _integer("CELEBRITY_V139_OPENAI_TIMEOUT_S", 420, 90, 900)
    body = {
        "model": model,
        "prompt": prompt,
        "size": selfie._openai_size(aspect),
        "quality": "high",
        "output_format": "jpeg",
        "n": 1,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=240), follow_redirects=True) as client:
        response = await client.post(
            base_url + "/images/generations",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
            json=body,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI scene HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        row = rows[0] if isinstance(rows, list) and rows else {}
        raw: bytes | None = None
        if isinstance(row, dict) and isinstance(row.get("b64_json"), str):
            raw = base64.b64decode(row["b64_json"])
        elif isinstance(row, dict) and isinstance(row.get("url"), str):
            image_response = await client.get(row["url"])
            image_response.raise_for_status()
            raw = image_response.content
        if not raw:
            raise RuntimeError("OpenAI scene returned no image")
        return _jpeg(raw)


async def _make_scene_candidates(mod: Any, scene: str, aspect: str, debug: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    jobs: list[tuple[str, str, Callable[[], Awaitable[bytes]]]] = []

    if selfie.previous._gemini_key(mod) and _flag("CELEBRITY_V139_GEMINI_SCENE_ENABLED", True):
        models = selfie.previous._gemini_models(mod)
        count = _integer("CELEBRITY_V139_GEMINI_SCENES", 2, 0, 4)
        for index in range(count):
            model = models[index % len(models)] if models else "gemini-3-pro-image"
            jobs.append((
                f"scene_gemini_{index + 1}",
                f"gemini:{model}",
                lambda model=model, index=index: selfie._gemini_generate(
                    mod, model, _scene_prompt(scene, aspect, index), [], aspect=aspect
                ),
            ))

    if selfie._openai_key(mod) and _flag("CELEBRITY_V139_OPENAI_SCENE_ENABLED", True):
        jobs.append((
            "scene_openai_1",
            "openai:gpt-image-1",
            lambda: _openai_generate(mod, _scene_prompt(scene, aspect, 2), aspect=aspect),
        ))

    if selfie._bfl_key() and _flag("CELEBRITY_V139_FLUX_SCENE_ENABLED", True):
        jobs.append((
            "scene_flux_1",
            f"bfl:{os.environ.get('CELEBRITY_FLUX_MODEL') or 'flux-2-pro'}",
            lambda: selfie._flux_edit(_scene_prompt(scene, aspect, 1), [], aspect),
        ))

    semaphore = asyncio.Semaphore(_integer("CELEBRITY_V139_SCENE_PARALLEL", 2, 1, 3))

    async def run_job(name: str, provider: str, factory: Callable[[], Awaitable[bytes]]) -> None:
        async with semaphore:
            stage = _stage_start(debug, name, provider)
            try:
                raw = await factory()
                problem = _structural_problem(raw, name)
                if problem:
                    raise PipelineError("structural_qc", problem)
                score = _structural_score(raw)
                candidate = {"label": name, "provider": provider, "score": score, "output": raw}
                candidates.append(candidate)
                debug["scene_candidates"].append({key: value for key, value in candidate.items() if key != "output"})
                _stage_finish(stage, "ok", score=score, bytes=len(raw))
            except Exception as exc:
                _record_error(debug, stage, exc)

    if jobs:
        await asyncio.gather(*(run_job(*job) for job in jobs))
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


def _side_index(side: str) -> str:
    return "0" if side == "left" else "1"


async def _piapi_single_face(mod: Any, target: bytes, reference: bytes, side: str) -> bytes:
    source = _face_crop(reference, 1152)
    target = _jpeg(target, max_side=2200, quality=96)
    output = await pi_identity._piapi_task(
        mod,
        "multi-face-swap",
        {
            "swap_image": base64.b64encode(source).decode("ascii"),
            "target_image": base64.b64encode(target).decode("ascii"),
            "swap_faces_index": "0",
            "target_faces_index": _side_index(side),
        },
    )
    return _jpeg(output)


async def _openai_single_face(
    mod: Any,
    target: bytes,
    references: list[bytes],
    side: str,
    identity_label: str,
    aspect: str,
    *,
    repair: bool = False,
) -> bytes:
    images: list[tuple[str, bytes]] = [("accepted-scene.jpg", _jpeg(target))]
    for index, raw in enumerate(references[:3], start=1):
        images.append((f"identity-reference-{index}.jpg", _face_crop(raw, 1152)))
    return await selfie._openai_edit(
        mod,
        _identity_edit_prompt(side, identity_label, repair=repair),
        images,
        aspect=aspect,
    )


def _encode_board(images: list[Image.Image], height: int = 640) -> bytes:
    resized: list[Image.Image] = []
    for image in images:
        ratio = height / max(1, image.height)
        resized.append(image.resize((max(1, int(image.width * ratio)), height), Image.Resampling.LANCZOS))
    board = Image.new("RGB", (sum(image.width for image in resized), height), (24, 24, 24))
    x = 0
    for image in resized:
        board.paste(image, (x, 0))
        x += image.width
    out = BytesIO()
    board.save(out, "JPEG", quality=93, optimize=True)
    return out.getvalue()


def _json_object(text: str) -> dict[str, Any] | None:
    with contextlib.suppress(Exception):
        value = json.loads(str(text or "").strip())
        if isinstance(value, dict):
            return value
    start = str(text or "").find("{")
    end = str(text or "").rfind("}")
    if start >= 0 and end > start:
        with contextlib.suppress(Exception):
            value = json.loads(str(text)[start:end + 1])
            if isinstance(value, dict):
                return value
    return None


async def _side_identity_score(mod: Any, output: bytes, reference: bytes, side: str) -> dict[str, Any]:
    problem = _structural_problem(output, f"{side}-identity")
    if problem:
        return {"score": 0.0, "structural_ok": False, "reason": problem, "unknown": False}

    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision) or not _flag("CELEBRITY_V139_VISION_QC", True):
        return {"score": 50.0, "structural_ok": True, "reason": "vision-qc-unavailable", "unknown": True}

    ref_image = ImageOps.fit(Image.open(BytesIO(_face_crop(reference, 640))).convert("RGB"), (640, 640), method=Image.Resampling.LANCZOS)
    result_image = ImageOps.fit(Image.open(BytesIO(output)).convert("RGB"), (900, 640), method=Image.Resampling.LANCZOS)
    board = _encode_board([ref_image, result_image], height=640)
    prompt = (
        "Quality-control board: LEFT panel is an identity reference; RIGHT panel is a generated photo with two foreground "
        f"people. Do not identify or name anyone. Compare the reference only to the {side.upper()} foreground face in the "
        "generated photo. Return strict JSON only: similarity integer 0-100, two_distinct_foreground_people boolean, "
        "target_face_visible boolean, other_face_preserved boolean, reason short string. Allow ordinary lighting, expression "
        "and lens changes, but penalize changed head shape, hairline, eye spacing, nose, lips and jaw."
    )
    try:
        answer = await vision(prompt, base64.b64encode(board).decode("ascii"), "image/jpeg")
        data = _json_object(answer) or {}
        score = max(0.0, min(100.0, float(data.get("similarity") or 0)))
        if data.get("two_distinct_foreground_people") is False or data.get("target_face_visible") is False:
            score = 0.0
        if score <= 0:
            return {"score": 50.0, "structural_ok": True, "reason": str(data.get("reason") or "vision score missing")[:300], "unknown": True}
        return {
            "score": round(score, 1),
            "structural_ok": True,
            "reason": str(data.get("reason") or "ok")[:300],
            "unknown": False,
            "other_face_preserved": data.get("other_face_preserved"),
        }
    except Exception as exc:
        return {"score": 50.0, "structural_ok": True, "reason": f"vision-qc-error:{_safe_error(exc)}"[:300], "unknown": True}


async def _identity_variants(
    mod: Any,
    target: bytes,
    references: list[bytes],
    side: str,
    identity_label: str,
    aspect: str,
    debug: dict[str, Any],
    parent_label: str,
    *,
    repair: bool = False,
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    providers = [item.strip().casefold() for item in str(os.environ.get("CELEBRITY_V139_IDENTITY_PROVIDERS") or "piapi,openai").split(",") if item.strip()]
    stop_score = _number("CELEBRITY_V139_IDENTITY_STOP_SCORE", 76.0, 50.0, 95.0)

    for provider in providers:
        if provider == "piapi" and not pi_identity._piapi_key(mod):
            continue
        if provider == "openai" and not selfie._openai_key(mod):
            continue
        label = f"{parent_label}_{side}_{provider}{'_repair' if repair else ''}"
        stage = _stage_start(debug, label, provider, side=side, repair=repair)
        try:
            if provider == "piapi":
                raw = await _piapi_single_face(mod, target, references[0], side)
            elif provider == "openai":
                raw = await _openai_single_face(mod, target, references, side, identity_label, aspect, repair=repair)
            else:
                continue
            problem = _structural_problem(raw, label)
            if problem:
                raise PipelineError("structural_qc", problem)
            qc = await _side_identity_score(mod, raw, references[0], side)
            if not qc.get("structural_ok"):
                raise PipelineError("structural_qc", str(qc.get("reason") or "identity output invalid"))
            score = float(qc.get("score") or 0)
            row = {
                "label": label,
                "provider": provider,
                "side": side,
                "score": round(score, 1),
                "unknown": bool(qc.get("unknown")),
                "reason": qc.get("reason"),
                "output": raw,
            }
            variants.append(row)
            debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
            _stage_finish(stage, "ok", score=round(score, 1), unknown=bool(qc.get("unknown")), bytes=len(raw))
            if score >= stop_score and not qc.get("unknown"):
                break
        except Exception as exc:
            _record_error(debug, stage, exc)

    variants.sort(key=lambda item: (not bool(item.get("unknown")), float(item.get("score") or 0)), reverse=True)
    return variants


async def _final_identity_qc(mod: Any, output: bytes, user_ref: bytes, celebrity_ref: bytes) -> dict[str, Any]:
    problem = _structural_problem(output, "final")
    if problem:
        return {"user": 0.0, "celebrity": 0.0, "minimum": 0.0, "weighted": 0.0, "unknown": False, "reason": problem}
    result = await selfie._identity_detail_qc(mod, output, user_ref, celebrity_ref)
    user = float(result.get("user") or 0)
    celebrity = float(result.get("celebrity") or 0)
    minimum = float(result.get("minimum") or min(user, celebrity))
    if minimum <= 0:
        left = await _side_identity_score(mod, output, user_ref, "left")
        right = await _side_identity_score(mod, output, celebrity_ref, "right")
        user = float(left.get("score") or 50)
        celebrity = float(right.get("score") or 50)
        minimum = min(user, celebrity)
        unknown = bool(left.get("unknown")) or bool(right.get("unknown"))
        return {
            "user": round(user, 1),
            "celebrity": round(celebrity, 1),
            "minimum": round(minimum, 1),
            "weighted": round(user * 0.55 + celebrity * 0.45, 1),
            "unknown": unknown,
            "reason": f"side-qc-fallback:{left.get('reason')}|{right.get('reason')}"[:400],
        }
    return {
        "user": round(user, 1),
        "celebrity": round(celebrity, 1),
        "minimum": round(minimum, 1),
        "weighted": round(float(result.get("weighted") or (user * 0.55 + celebrity * 0.45)), 1),
        "unknown": bool(result.get("identity_unknown")),
        "reason": str(result.get("reason") or "ok")[:400],
    }


async def _process_scene(
    mod: Any,
    scene_candidate: dict[str, Any],
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    finals: list[dict[str, Any]] = []
    scene_label = str(scene_candidate["label"])

    user_variants = await _identity_variants(
        mod,
        scene_candidate["output"],
        user_refs,
        "left",
        "the USER shown in the reference images",
        aspect,
        debug,
        scene_label,
    )
    if not user_variants:
        return finals

    user_limit = _integer("CELEBRITY_V139_USER_VARIANTS_TO_CONTINUE", 2, 1, 3)
    for user_variant in user_variants[:user_limit]:
        celebrity_variants = await _identity_variants(
            mod,
            user_variant["output"],
            celebrity_refs,
            "right",
            f"the selected PUBLIC PERSON ({celebrity_name}) shown in the reference images",
            aspect,
            debug,
            str(user_variant["label"]),
        )
        for celebrity_variant in celebrity_variants[:2]:
            qc = await _final_identity_qc(mod, celebrity_variant["output"], user_refs[0], celebrity_refs[0])
            if float(qc.get("minimum") or 0) <= 0:
                continue
            structural = _structural_score(celebrity_variant["output"])
            total = float(qc["minimum"]) * 0.58 + float(qc["weighted"]) * 0.30 + structural * 0.12
            row = {
                "label": celebrity_variant["label"],
                "scene": scene_label,
                "user_provider": user_variant["provider"],
                "celebrity_provider": celebrity_variant["provider"],
                "user_identity": qc["user"],
                "celebrity_identity": qc["celebrity"],
                "identity_min": qc["minimum"],
                "identity_weighted": qc["weighted"],
                "identity_unknown": bool(qc.get("unknown")),
                "structural": round(structural, 1),
                "total": round(total, 1),
                "reason": qc.get("reason"),
                "output": celebrity_variant["output"],
            }
            finals.append(row)

    return finals


async def _repair_weak_side(
    mod: Any,
    best: dict[str, Any],
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> dict[str, Any]:
    threshold = _number("CELEBRITY_V139_REPAIR_BELOW", 72.0, 45.0, 95.0)
    user_score = float(best.get("user_identity") or 0)
    celebrity_score = float(best.get("celebrity_identity") or 0)
    if min(user_score, celebrity_score) >= threshold or not _flag("CELEBRITY_V139_WEAK_SIDE_REPAIR", True):
        return best

    side = "left" if user_score <= celebrity_score else "right"
    refs = user_refs if side == "left" else celebrity_refs
    label = "the USER" if side == "left" else f"the selected PUBLIC PERSON ({celebrity_name})"
    variants = await _identity_variants(
        mod,
        best["output"],
        refs,
        side,
        label,
        aspect,
        debug,
        str(best["label"]),
        repair=True,
    )
    for variant in variants:
        qc = await _final_identity_qc(mod, variant["output"], user_refs[0], celebrity_refs[0])
        if float(qc.get("minimum") or 0) <= 0:
            continue
        structural = _structural_score(variant["output"])
        total = float(qc["minimum"]) * 0.58 + float(qc["weighted"]) * 0.30 + structural * 0.12
        candidate = {
            **best,
            "label": variant["label"],
            "user_identity": qc["user"],
            "celebrity_identity": qc["celebrity"],
            "identity_min": qc["minimum"],
            "identity_weighted": qc["weighted"],
            "identity_unknown": bool(qc.get("unknown")),
            "structural": round(structural, 1),
            "total": round(total, 1),
            "reason": qc.get("reason"),
            "output": variant["output"],
            "repair_side": side,
            "repair_provider": variant["provider"],
        }
        if float(candidate["total"]) > float(best["total"]) and float(candidate["identity_min"]) >= float(best["identity_min"]):
            return candidate
    return best


async def _emergency_one_shot(
    mod: Any,
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    aspect: str,
    debug: dict[str, Any],
) -> dict[str, Any] | None:
    if not _flag("CELEBRITY_V139_ONE_SHOT_FALLBACK", True) or not selfie._openai_key(mod):
        return None
    stage = _stage_start(debug, "emergency_one_shot", "openai:gpt-image-1")
    try:
        best_ref = celebrity_refs[0]
        raw = await selfie._openai_candidate(
            mod,
            user_refs[0],
            user_refs[1:],
            best_ref,
            celebrity_refs,
            celebrity_name,
            scene,
            aspect,
        )
        problem = _structural_problem(raw, "emergency-one-shot")
        if problem:
            raise PipelineError("structural_qc", problem)
        qc = await _final_identity_qc(mod, raw, user_refs[0], best_ref)
        structural = _structural_score(raw)
        total = float(qc["minimum"]) * 0.58 + float(qc["weighted"]) * 0.30 + structural * 0.12
        row = {
            "label": "emergency_one_shot",
            "scene": "one-shot-fallback",
            "user_provider": "openai",
            "celebrity_provider": "openai",
            "user_identity": qc["user"],
            "celebrity_identity": qc["celebrity"],
            "identity_min": qc["minimum"],
            "identity_weighted": qc["weighted"],
            "identity_unknown": bool(qc.get("unknown")),
            "structural": round(structural, 1),
            "total": round(total, 1),
            "reason": qc.get("reason"),
            "output": raw,
        }
        _stage_finish(stage, "ok", score=row["total"], identity_min=row["identity_min"])
        return row
    except Exception as exc:
        _record_error(debug, stage, exc)
        return None


async def _run_two_stage_generation(
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
        raise PipelineError("input", "User selfie is missing")
    if not celebrity_refs:
        raise PipelineError("input", "Public-person references are missing")

    aspect = selfie._aspect_for_scene(scene)
    debug = _new_debug(celebrity_name, scene, aspect)
    user_refs = [user_photo, *[raw for raw in (additional_user_refs or []) if raw]]
    best_public_ref = await selfie.impl._best_reference(celebrity_refs)
    public_refs = [best_public_ref, *[raw for raw in celebrity_refs if raw is not best_public_ref]]

    try:
        if previous_result:
            problem = _structural_problem(previous_result, "previous-result")
            if problem:
                raise PipelineError("structural_qc", problem)
            scenes = [{"label": "accepted_previous_scene", "provider": "previous", "score": _structural_score(previous_result), "output": previous_result}]
            debug["scene_candidates"].append({key: value for key, value in scenes[0].items() if key != "output"})
        else:
            scenes = await _make_scene_candidates(mod, scene, aspect, debug)

        if not scenes:
            debug["failure_class"] = "scene_generation"
            raise PipelineError("scene_generation", "No structurally valid scene candidate was returned", debug=debug)

        finals: list[dict[str, Any]] = []
        scene_limit = _integer("CELEBRITY_V139_SCENES_TO_IDENTITY", 2, 1, 3)
        for scene_candidate in scenes[:scene_limit]:
            finals.extend(await _process_scene(mod, scene_candidate, user_refs, public_refs, celebrity_name, aspect, debug))

        if not finals:
            emergency = await _emergency_one_shot(mod, user_refs, public_refs, celebrity_name, scene, aspect, debug)
            if emergency:
                finals.append(emergency)

        if not finals:
            categories = [str(item.get("category") or "") for item in debug.get("errors", [])]
            category = "identity_providers" if any(item in categories for item in ("auth_or_key", "provider_error", "timeout", "rate_limit")) else "identity_pipeline"
            debug["failure_class"] = category
            raise PipelineError(category, "Scene drafts were created, but no identity-locked result survived", debug=debug)

        finals.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
        best = finals[0]
        best = await _repair_weak_side(mod, best, user_refs, public_refs, celebrity_name, aspect, debug)

        debug["selected"] = {key: value for key, value in best.items() if key != "output"}
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        debug["failure_class"] = None
        _LAST_RUN_DEBUG = _public_debug(debug)
        return best["output"], _LAST_RUN_DEBUG
    except PipelineError as exc:
        debug["failure_class"] = exc.category
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        _LAST_RUN_DEBUG = _public_debug(debug)
        exc.debug = _LAST_RUN_DEBUG
        raise
    except Exception as exc:
        category = _classify_error(exc)
        debug["failure_class"] = category
        debug["errors"].append({"stage": "pipeline", "provider": "internal", "category": category, "error": _safe_error(exc)})
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        _LAST_RUN_DEBUG = _public_debug(debug)
        raise PipelineError(category, _safe_error(exc), debug=_LAST_RUN_DEBUG) from exc


def _delivery_state(selected: dict[str, Any]) -> tuple[str, float]:
    score = float(selected.get("identity_min") or 0)
    threshold = _number("CELEBRITY_V139_VERIFIED_IDENTITY", 62.0, 40.0, 90.0)
    return ("preview", score) if selected.get("identity_unknown") or score < threshold else ("verified", score)


def _failure_message(exc: BaseException, debug: dict[str, Any]) -> str:
    category = getattr(exc, "category", None) or debug.get("failure_class") or _classify_error(exc)
    messages = {
        "scene_generation": "Провайдеры не вернули ни одной исправной двухместной сцены.",
        "auth_or_key": "Один из модулей генерации или переноса лица не авторизован.",
        "timeout": "Провайдер превысил время ожидания.",
        "rate_limit": "Провайдер временно ограничил частоту запросов.",
        "safety_block": "Провайдер заблокировал запрос своим фильтром безопасности.",
        "malformed_response": "Провайдер завершил задачу без пригодного файла изображения.",
        "structural_qc": "Полученные кадры содержали техническую склейку или не имели двух пригодных лиц.",
        "identity_providers": "Сцена создана, но модули последовательного переноса лиц не вернули пригодный результат.",
        "identity_pipeline": "Сцена создана, но после последовательной фиксации лиц результат потерял целостность.",
        "provider_error": "Один из внешних провайдеров вернул техническую ошибку.",
    }
    return messages.get(str(category), "Конвейер остановился из-за технической ошибки.")


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    engine = selfie.engine
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Откройте режим заново.")
        return

    now = time.monotonic()
    if str(session.get("state") or "") in {"queued", "generating"} and now - float(session.get("generation_started_monotonic") or 0) < 1800:
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

    previous_result = engine._read_path(session.get("result_path")) if refinement else None
    generation_id = uuid.uuid4().hex
    session.update({
        "generation_id": generation_id,
        "generation_started_monotonic": now,
        "generation_scene_snapshot": scene,
        "generation_celebrity_snapshot": celebrity_name,
        "state": "queued",
    })

    async def work() -> bool:
        if not selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            return False
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Этап 1/3: создаю чистую сцену с двумя людьми. Затем отдельно закреплю ваше лицо слева и лицо выбранного человека справа. "
            "Обычно это занимает 3–8 минут."
        )
        try:
            output, debug = await _run_two_stage_generation(
                mod,
                user_photo,
                refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
                additional_user_refs=[second_user] if second_user else [],
            )
        except Exception as exc:
            debug = getattr(exc, "debug", None) or _LAST_RUN_DEBUG or {}
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "result" if previous_result else "await_scene"
                session["v139_debug"] = _public_debug(debug) if isinstance(debug, dict) else {}
                session["last_generation_error"] = _safe_error(exc)
                session["last_generation_failed_at"] = time.time()
                session["generation_failures"] = int(session.get("generation_failures") or 0) + 1
                session.pop("generation_id", None)
                run_id = str((debug or {}).get("run_id") or "-")
                await update.effective_message.reply_text(
                    "❌ Генерация остановлена. " + _failure_message(exc, debug or {}) +
                    f"\nКод диагностики: {run_id}. Кредиты за невыданный результат не должны списываться.",
                    reply_markup=selfie.v133._failure_kb(),
                )
            return False

        if not selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            if str(session.get("generation_id") or "") == generation_id:
                session.pop("generation_id", None)
            return False

        selected = debug.get("selected") or {}
        delivery_mode, identity_min = _delivery_state(selected)
        session["v139_debug"] = _public_debug(debug)
        session["delivery_mode"] = delivery_mode
        session["delivery_identity_min"] = identity_min
        session["result_path"] = engine._store_image(session, "result_refined.jpg" if refinement else "result.jpg", output)
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session["generation_failures"] = 0
        session.pop("generation_id", None)

        from telegram import InputFile
        bio = BytesIO(output)
        bio.name = "celebrity_selfie.jpg"
        if delivery_mode == "verified":
            title = "📸 AI-селфи готово ✅"
            quality = f"Оба лица прошли раздельную проверку; минимальная оценка сходства {identity_min:.0f}/100."
        else:
            title = "📸 Предварительный AI-результат"
            quality = (
                f"Кадр структурно исправен, но минимальная оценка сходства {identity_min:.0f}/100 ниже целевой. "
                "Он показан для визуальной оценки; можно нажать улучшение или повторить сцену."
            )
        caption = (
            f"{title}\n"
            f"Персона: {celebrity_name}\n"
            f"Архитектура: сцена → ваше лицо → второе лицо → ремонт слабой стороны.\n"
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
    cost = float(os.environ.get("CELEBRITY_V139_UNIT_COST_USD") or os.environ.get("CELEBRITY_V136_UNIT_COST_USD") or 0.80)
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind="celebrity_selfie_v139_refine" if refinement else "celebrity_selfie_v139",
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "refinement": refinement,
            "generation_id": generation_id,
            "pipeline": VERSION,
            "architecture": "scene+left+right+repair",
            "nano_banana_comet": False,
            "aspect": selfie._aspect_for_scene(scene),
            "user_references": 2 if second_user else 1,
        },
    )


def _format_stage(stage: dict[str, Any]) -> str:
    name = str(stage.get("name") or "-")
    provider = str(stage.get("provider") or "-")
    status = str(stage.get("status") or "-")
    duration = stage.get("duration_s")
    extra = ""
    if stage.get("score") is not None:
        extra += f" score={stage.get('score')}"
    if stage.get("category"):
        extra += f" category={stage.get('category')}"
    if stage.get("error"):
        extra += f" error={str(stage.get('error'))[:180]}"
    return f"- {name} [{provider}] {status} {duration if duration is not None else '-'}s{extra}"[:500]


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = selfie.engine._session(context, create=False)
    debug = (session or {}).get("v139_debug") or _LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    stages = debug.get("stages") or []
    errors = debug.get("errors") or []
    mod = selfie.engine._runtime_module()
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=scene_first+left_identity+right_identity+weak_side_repair",
        "nano_banana_comet=disabled",
        f"run_id={debug.get('run_id', '-')}",
        f"state={(session or {}).get('state', '-')}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"identity_candidates={len(debug.get('identity_candidates') or [])}",
        f"piapi={'ready' if (mod is not None and bool(pi_identity._piapi_key(mod))) else 'missing'}",
        f"openai_images={'ready' if (mod is not None and bool(selfie._openai_key(mod))) else 'missing'}",
        f"gemini_direct={'ready' if (mod is not None and bool(selfie.previous._gemini_key(mod))) else 'missing'}",
        f"flux={'ready' if bool(selfie._bfl_key()) else 'optional-missing'}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"delivery_mode={(session or {}).get('delivery_mode', '-')}",
        f"selected={str(selected or '-')[:950]}",
        f"last_error={(session or {}).get('last_generation_error', '-')}",
        "stages:",
    ]
    lines.extend(_format_stage(item) for item in stages[-10:])
    if errors:
        lines.append("errors:")
        for item in errors[-5:]:
            lines.append(
                f"- {item.get('stage')} [{item.get('provider')}] {item.get('category')}: {str(item.get('error') or '')[:220]}"
            )
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


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
    output, _ = await _run_two_stage_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def install_runtime_patches() -> None:
    os.environ.setdefault("CELEBRITY_V139_UNIT_COST_USD", "0.80")
    os.environ.setdefault("CELEBRITY_V139_GEMINI_SCENES", "2")
    os.environ.setdefault("CELEBRITY_V139_SCENES_TO_IDENTITY", "2")
    os.environ.setdefault("CELEBRITY_V139_IDENTITY_PROVIDERS", "piapi,openai")
    os.environ.setdefault("CELEBRITY_V139_IDENTITY_STOP_SCORE", "76")
    os.environ.setdefault("CELEBRITY_V139_REPAIR_BELOW", "72")
    os.environ.setdefault("CELEBRITY_V139_VERIFIED_IDENTITY", "62")
    os.environ.setdefault("CELEBRITY_V139_ONE_SHOT_FALLBACK", "1")
    os.environ.setdefault("CELEBRITY_V139_WEAK_SIDE_REPAIR", "1")
    os.environ.setdefault("CELEBRITY_V139_VISION_QC", "1")
    os.environ.setdefault("CELEBRITY_NATIVE_PIAPI_REPAIR", "0")

    selfie._run_v139_generation = _run_two_stage_generation
    selfie._run_v136_generation = _run_compat
    selfie._generate = _generate
    selfie.engine._run_multi_reference_generation = _run_compat
    selfie.engine._generate = _generate
    selfie.engine._diag = _diag


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
            for command in ("diag_celebrity_flow", "diag_selfie_v139", "diag_brand"):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


install_runtime_patches()

__all__ = [
    "VERSION", "PipelineError", "install_runtime_patches", "install_builder_hook",
    "_scene_prompt", "_identity_edit_prompt", "_openai_generate", "_make_scene_candidates",
    "_piapi_single_face", "_openai_single_face", "_side_identity_score",
    "_identity_variants", "_final_identity_qc", "_process_scene", "_repair_weak_side",
    "_run_two_stage_generation", "_run_compat", "_generate", "_diag",
]
