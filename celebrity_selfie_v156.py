# -*- coding: utf-8 -*-
"""Celebrity Selfie v156: Comet best-of-N dual-identity render.

This release removes the production cut-and-paste celebrity route. The complete
scene is generated as one coherent photograph from separate user and public-
figure identity references, then ranked and (when needed) repaired through the
same Comet multimodal provider. No local rembg, ONNX, PhotoRoom compositing,
PiAPI face swap, direct Gemini key, or direct OpenAI Images key is used by this
feature. PhotoRoom remains available to the independent background-removal tool.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import gc
import logging
import os
import time
import uuid
from io import BytesIO
from typing import Any, Iterable

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

import celebrity_selfie_v139 as v139
import celebrity_selfie_v150 as v150

VERSION = "v156-comet-dual-identity-best-of-n-2026-07-23"
_GROUP = -2_100_002_000
_BUILDER_FLAG = "_celebrity_selfie_v156_builder"
_HANDLER_FLAG = "_celebrity_selfie_v156_handlers"
_INSTALL_FLAG = "_celebrity_selfie_v156_installed"

log = logging.getLogger("gpt-bot.celebrity-selfie-v156")
_LAST_RUN_DEBUG: dict[str, Any] = {}
_AUTH_DISABLED: dict[str, str] = {}
_GENERATION_GATE: asyncio.Semaphore | None = None
_ORIGINAL_CALLBACK = v139.selfie.engine._on_callback


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.environ.get(name) or default).replace(",", "."))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return int(round(_number(name, float(default), float(minimum), float(maximum))))


def _runtime_value(mod: Any, name: str, default: str = "") -> str:
    return str(getattr(mod, name, "") or os.environ.get(name) or default).strip()


def _safe_error(exc: BaseException) -> str:
    with contextlib.suppress(Exception):
        return v139._safe_error(exc)
    return f"{type(exc).__name__}: {exc}"[:1800]


def _rss_mb() -> float:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _generation_gate() -> asyncio.Semaphore:
    global _GENERATION_GATE
    if _GENERATION_GATE is None:
        _GENERATION_GATE = asyncio.Semaphore(_integer("CELEBRITY_V156_MAX_CONCURRENCY", 1, 1, 2))
    return _GENERATION_GATE


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int = 95) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _normalise_output(raw: bytes, aspect: str) -> bytes:
    image = _open_rgb(raw)
    safe = str(aspect or "4:5")
    try:
        left, right = safe.split(":", 1)
        ratio = float(left) / max(0.01, float(right))
    except Exception:
        ratio = 0.8
    long_side = _integer("CELEBRITY_V156_OUTPUT_LONG_SIDE", 1536, 1024, 2048)
    if ratio >= 1.0:
        target = (long_side, max(768, int(long_side / ratio)))
    else:
        target = (max(768, int(long_side * ratio)), long_side)
    image = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return _encode_jpeg(image, 95)


def _face_boxes(raw: bytes) -> list[dict[str, Any]]:
    with contextlib.suppress(Exception):
        return [dict(item) for item in (v139.selfie.base._face_boxes(raw) or []) if isinstance(item, dict)]
    return []


def _face_crop(raw: bytes, max_side: int = 896) -> bytes:
    with contextlib.suppress(Exception):
        result = v139._face_crop(raw, max_side)
        if result:
            return bytes(result)
    image = _open_rgb(raw)
    side = min(image.size)
    left = max(0, (image.width - side) // 2)
    top = max(0, min(image.height - side, int((image.height - side) * 0.30)))
    crop = image.crop((left, top, left + side, top + side))
    crop.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return _encode_jpeg(crop, 95)


def _image_metrics(raw: bytes) -> dict[str, float]:
    image = _open_rgb(raw)
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    edge = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES))
    return {
        "width": float(image.width),
        "height": float(image.height),
        "short_side": float(min(image.size)),
        "brightness": float(stat.mean[0]),
        "contrast": float(stat.stddev[0]),
        "sharpness": float(edge.var[0] ** 0.5),
    }


def _json_object(text: str) -> dict[str, Any]:
    for name in ("_json_object", "_extract_json"):
        with contextlib.suppress(Exception):
            value = getattr(v139, name)(text)
            if isinstance(value, dict):
                return value
    return {}


def _reference_local_score(raw: bytes) -> tuple[float, dict[str, Any]]:
    image = _open_rgb(raw)
    metrics = _image_metrics(raw)
    boxes = _face_boxes(raw)
    score = min(28.0, metrics["short_side"] / 36.0)
    score += min(18.0, metrics["contrast"] * 0.55)
    score += min(18.0, metrics["sharpness"] * 0.40)
    face_ratio = 0.0
    if len(boxes) == 1:
        face = boxes[0]
        face_ratio = float(face.get("w") or 0) * float(face.get("h") or 0) / max(1.0, image.width * image.height)
        score += 60.0
        if 0.035 <= face_ratio <= 0.55:
            score += 22.0
    elif len(boxes) == 0:
        score -= 30.0
    else:
        score -= 38.0 + 8.0 * (len(boxes) - 1)
    return score, {
        "score": round(score, 2),
        "faces": len(boxes),
        "face_ratio": round(face_ratio, 4),
        "size": [image.width, image.height],
    }


def _reference_board(refs: list[bytes]) -> bytes:
    refs = refs[:4]
    tile = 512
    board = Image.new("RGB", (tile * 2, tile * 2), (20, 20, 20))
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default()
    for index, raw in enumerate(refs):
        image = ImageOps.fit(_open_rgb(raw), (tile, tile), method=Image.Resampling.LANCZOS, centering=(0.5, 0.34))
        x, y = (index % 2) * tile, (index // 2) * tile
        board.paste(image, (x, y))
        draw.rounded_rectangle((x + 12, y + 12, x + 84, y + 54), radius=9, fill=(0, 0, 0))
        draw.text((x + 35, y + 22), str(index + 1), fill=(255, 255, 255), font=font)
    return _encode_jpeg(board, 93)


async def _rank_celebrity_references(mod: Any, refs: list[bytes], debug: dict[str, Any]) -> list[bytes]:
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(refs[:8]):
        try:
            score, details = _reference_local_score(raw)
            rows.append({"source_index": index + 1, "raw": raw, **details})
        except Exception as exc:
            rows.append({"source_index": index + 1, "raw": raw, "score": -9999.0, "error": _safe_error(exc)})
    rows.sort(key=lambda item: float(item.get("score") or -9999), reverse=True)
    debug["reference_local_ranking"] = [{k: v for k, v in row.items() if k != "raw"} for row in rows]
    rows = [row for row in rows if row.get("raw")]
    if not rows:
        raise v139.PipelineError("reference", "No readable public-person reference was supplied", debug=debug)

    shortlist = rows[:4]
    vision = getattr(mod, "ask_openai_vision", None)
    if callable(vision) and _flag("CELEBRITY_V156_REFERENCE_VISION_QC", True):
        prompt = (
            "Numbered panels are candidate reference photos of the same public figure. Do not identify anyone. "
            "Rank usefulness for photorealistic identity conditioning. Reject wax figures, statues, mannequins, museum exhibits, "
            "posters, paintings, screenshots, photos behind glass, plaques/labels attached to the subject, tiny or blurred faces, "
            "masks, and images dominated by other people. Return strict JSON only: "
            "{\"items\":[{\"index\":1,\"usable\":true,\"real_human_photo\":true,\"wax_or_exhibit\":false,"
            "\"face_quality\":0,\"identity_usefulness\":0,\"reason\":\"\"}],\"ranking\":[1,2,3,4]}."
        )
        try:
            board = _reference_board([row["raw"] for row in shortlist])
            answer = await vision(prompt, base64.b64encode(board).decode("ascii"), "image/jpeg")
            data = _json_object(answer)
            by_index: dict[int, dict[str, Any]] = {}
            for item in data.get("items") or []:
                if isinstance(item, dict):
                    with contextlib.suppress(Exception):
                        idx = int(item.get("index") or 0)
                        if 1 <= idx <= len(shortlist):
                            by_index[idx] = item
            order: list[int] = []
            for value in data.get("ranking") or []:
                with contextlib.suppress(Exception):
                    idx = int(value)
                    if 1 <= idx <= len(shortlist) and idx not in order:
                        order.append(idx)
            order.extend(idx for idx in range(1, len(shortlist) + 1) if idx not in order)
            accepted: list[bytes] = []
            qc_rows: list[dict[str, Any]] = []
            for idx in order:
                row = shortlist[idx - 1]
                qc = by_index.get(idx, {})
                quality = float(qc.get("face_quality") or 0)
                usefulness = float(qc.get("identity_usefulness") or 0)
                ok = (
                    qc.get("usable") is not False
                    and qc.get("real_human_photo") is not False
                    and qc.get("wax_or_exhibit") is not True
                    and max(quality, usefulness) >= 45
                )
                qc_rows.append({
                    "source_index": row["source_index"],
                    "accepted": ok,
                    "face_quality": quality,
                    "identity_usefulness": usefulness,
                    "reason": str(qc.get("reason") or "")[:260],
                })
                if ok:
                    accepted.append(row["raw"])
                if len(accepted) >= _integer("CELEBRITY_V156_CELEBRITY_REFERENCE_LIMIT", 3, 1, 4):
                    break
            debug["reference_vision_qc"] = qc_rows
            if accepted:
                return accepted
        except Exception as exc:
            debug.setdefault("reference_errors", []).append(_safe_error(exc))

    one_face = [row["raw"] for row in rows if int(row.get("faces") or 0) == 1]
    fallback = one_face or [row["raw"] for row in rows]
    return fallback[:_integer("CELEBRITY_V156_CELEBRITY_REFERENCE_LIMIT", 3, 1, 4)]


def _scene_profile(scene: str) -> str:
    text = str(scene or "").strip()
    low = text.casefold().replace("ё", "е")
    if "кремл" in low or "kremlin" in low:
        return "inside a grand ceremonial Kremlin hall with gilded classical architecture, polished floors and coherent warm chandelier lighting"
    if "красн" in low and "площад" in low:
        return "on Red Square in Moscow with coherent Kremlin and Saint Basil architecture in natural daylight"
    if "яхт" in low or "yacht" in low or "море" in low:
        return "on the open deck of one modern yacht at sea with coherent railings, horizon and daylight"
    if "ресторан" in low or "restaurant" in low:
        return "inside one modern upscale restaurant with warm practical lighting"
    if "премьер" in low or "дорожк" in low or "red carpet" in low:
        return "at a film-premiere red carpet with realistic event lighting and an abstract unreadable media wall"
    if "выстав" in low or "exhibition" in low:
        return "inside one contemporary public exhibition with subtle displays far in the background"
    return text or "a believable public event location"


def _attire_contract(scene: str) -> str:
    low = str(scene or "").casefold().replace("ё", "е")
    if any(token in low for token in ("костюм", "suit", "смокинг", "tuxedo")):
        return "Both adults wear realistic well-fitted dark formal suits and shirts; no sportswear, museum costume, jacket exhibit or casual outerwear."
    return "Both adults wear coherent contemporary clothing appropriate to the requested event."


def _scene_prompt(celebrity_name: str, scene: str, aspect: str, variant: int) -> str:
    framings = (
        "natural arm-length smartphone selfie, both heads and upper torsos visible at similar scale",
        "friendly shoulder-to-shoulder mobile photograph with equal eye line and realistic phone-lens perspective",
        "slightly wider premium candid smartphone selfie with environmental context and both faces still large",
    )
    return (
        "Create exactly ONE seamless photorealistic smartphone photograph in one continuous camera frame. "
        "Exactly TWO living adult people are physically together: USER on the LEFT and the selected public figure on the RIGHT. "
        "Use USER REFERENCE images only for the left person's facial identity and natural current appearance. "
        f"Use PUBLIC FIGURE REFERENCE images only for the right person's facial identity ({celebrity_name}). "
        "Never copy source backgrounds, source clothing, glass reflections, plaques, labels, museum stands, posters, text, body poses, or unrelated people from any reference. "
        "Both must look like real living humans photographed together, never wax figures, statues, mannequins, cardboard cutouts, paintings, holograms, museum exhibits or duplicated faces. "
        "Preserve each identity separately: do not blend faces, swap sides, beautify, age, de-age, change ethnicity, or invent look-alikes. "
        f"Location: {_scene_profile(scene)}. {_attire_contract(scene)} "
        f"Composition: {framings[variant % len(framings)]}. Portrait aspect {aspect}. "
        "Both faces frontal or gentle three-quarter, unobstructed, upright, similarly sized, naturally lit and in focus. "
        "Correct anatomy and hands, coherent perspective, one light direction, realistic skin texture, natural mobile HDR. "
        "No third prominent person, no crowd face near them, no collage, split screen, inset, frame, readable text, logo, watermark or plaque. Return only the final image."
    )


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _image_from_payload(data: Any) -> bytes | None:
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        for key in ("b64_json", "b64", "base64", "image_base64", "imageBase64", "data"):
            value = node.get(key)
            if isinstance(value, str) and len(value) > 120:
                with contextlib.suppress(Exception):
                    encoded = value.split(",", 1)[-1] if value.startswith("data:") else value
                    raw = base64.b64decode(encoded, validate=False)
                    _open_rgb(raw)
                    return raw
    return None


def _image_url(data: Any) -> str | None:
    for node in _walk(data):
        if isinstance(node, str) and node.startswith(("https://", "http://")):
            return node
        if isinstance(node, dict):
            for key in ("url", "image_url", "imageUrl", "download_url", "downloadUrl"):
                value = node.get(key)
                if isinstance(value, str) and value.startswith(("https://", "http://")):
                    return value
    return None


def _comet_key(mod: Any | None = None) -> str:
    return str(
        (getattr(mod, "COMET_API_KEY", "") if mod is not None else "")
        or os.environ.get("COMET_API_KEY")
        or os.environ.get("COMETAPI_KEY")
        or ""
    ).strip()


def _gemini_models() -> list[str]:
    raw = os.environ.get("CELEBRITY_V156_COMET_GEMINI_MODELS") or "gemini-2.5-flash-image,gemini-3-pro-image"
    models: list[str] = []
    for value in raw.split(","):
        model = value.strip().replace("gemini-2-5-", "gemini-2.5-")
        if model and "preview" not in model.casefold() and model not in models:
            models.append(model)
    return models or ["gemini-2.5-flash-image"]


def _image_part(mod: Any, raw: bytes, camel: bool) -> dict[str, Any]:
    return v139.selfie.engine._image_part(mod, _face_crop(raw, 896), 896, camel)


async def _comet_gemini_render(
    mod: Any,
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    prompt: str,
    aspect: str,
    debug: dict[str, Any],
    variant: int,
    *,
    draft: bytes | None = None,
    repair_side: str = "",
) -> bytes:
    if "comet" in _AUTH_DISABLED:
        raise v139.PipelineError("auth_or_key", f"Comet disabled: {_AUTH_DISABLED['comet']}", debug=debug)
    key = _comet_key(mod)
    if not key:
        raise v139.PipelineError("auth_or_key", "COMET_API_KEY missing", debug=debug)
    base = _runtime_value(mod, "COMET_BASE_URL", "https://api.cometapi.com").rstrip("/")
    template = os.environ.get("CELEBRITY_V156_COMET_GEMINI_PATH") or "/v1beta/models/{model}:generateContent"
    models = _gemini_models()
    model = models[variant % len(models)]
    url = base + (template if template.startswith("/") else "/" + template).replace("{model}", model)
    timeout_s = _integer("CELEBRITY_V156_COMET_TIMEOUT_S", 360, 90, 900)
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"}
    errors: list[str] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=35, read=timeout_s, write=180),
        follow_redirects=True,
    ) as client:
        for camel in (True, False):
            parts: list[dict[str, Any]] = [{"text": prompt}]
            if draft:
                parts.extend([
                    {"text": "CURRENT DRAFT TO EDIT. Preserve its scene, camera, bodies, clothing and composition unless explicitly instructed."},
                    v139.selfie.engine._image_part(mod, draft, 1280, camel),
                ])
            for index, raw in enumerate(user_refs[:2], start=1):
                parts.extend([
                    {"text": f"USER REFERENCE {index}: immutable LEFT identity cue; use face and current appearance only."},
                    _image_part(mod, raw, camel),
                ])
            for index, raw in enumerate(celebrity_refs[:3], start=1):
                parts.extend([
                    {"text": f"PUBLIC FIGURE REFERENCE {index}: immutable RIGHT identity cue; use face only and ignore all source context."},
                    _image_part(mod, raw, camel),
                ])
            config = {"responseModalities": ["TEXT", "IMAGE"]} if camel else {"response_modalities": ["TEXT", "IMAGE"]}
            payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
            schema = "camel" if camel else "snake"
            debug.setdefault("comet_attempts", []).append({
                "route": "gemini-generateContent",
                "model": model,
                "schema": schema,
                "variant": variant,
                "repair_side": repair_side or "none",
                "user_refs": len(user_refs[:2]),
                "celebrity_refs": len(celebrity_refs[:3]),
            })
            try:
                response = await client.post(url, headers=headers, json=payload)
                try:
                    data: Any = response.json()
                except Exception:
                    data = {"raw": response.text[:1200]}
                if response.status_code >= 400:
                    message = f"{model}/{schema} HTTP {response.status_code}: {str(data)[:700]}"
                    errors.append(message)
                    if response.status_code in {401, 403} or v150._looks_auth_error(message):
                        _AUTH_DISABLED["comet"] = message[:500]
                        raise v139.PipelineError("auth_or_key", message, debug=debug)
                    continue
                raw = None
                extractor = getattr(mod, "_image_bytes_from_response", None)
                if callable(extractor):
                    with contextlib.suppress(Exception):
                        raw = await extractor(response, client)
                if not raw:
                    raw = _image_from_payload(data)
                if not raw:
                    value = _image_url(data)
                    if value:
                        downloaded = await client.get(value, headers={"Accept": "image/*,*/*"})
                        if downloaded.status_code < 400 and downloaded.content:
                            raw = downloaded.content
                if raw:
                    return _normalise_output(raw, aspect)
                errors.append(f"{model}/{schema}: response contained no image")
            except v139.PipelineError:
                raise
            except Exception as exc:
                errors.append(f"{model}/{schema}: {_safe_error(exc)}")
    raise RuntimeError("Comet Gemini render failed: " + " | ".join(errors[-6:])[:1800])


async def _comet_openai_edit_render(
    mod: Any,
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    prompt: str,
    aspect: str,
    debug: dict[str, Any],
    variant: int,
) -> bytes:
    key = _comet_key(mod)
    if not key:
        raise v139.PipelineError("auth_or_key", "COMET_API_KEY missing", debug=debug)
    base = _runtime_value(mod, "COMET_BASE_URL", "https://api.cometapi.com").rstrip("/")
    path = os.environ.get("CELEBRITY_V156_COMET_OPENAI_EDIT_PATH") or "/v1/images/edits"
    model = os.environ.get("CELEBRITY_V156_COMET_OPENAI_MODEL") or "gpt-image-1"
    timeout_s = _integer("CELEBRITY_V156_COMET_TIMEOUT_S", 360, 90, 900)
    size = "1536x1024" if str(aspect).startswith(("16:", "3:2")) else "1024x1536"
    data = {"model": model, "prompt": prompt, "size": size, "quality": "high", "n": "1"}
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    images = [("user", raw) for raw in user_refs[:2]] + [("celebrity", raw) for raw in celebrity_refs[:3]]
    errors: list[str] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=35, read=timeout_s, write=180),
        follow_redirects=True,
    ) as client:
        for field in ("image[]", "image"):
            files = [(field, (f"{role}-{idx}.jpg", _face_crop(raw, 896), "image/jpeg")) for idx, (role, raw) in enumerate(images, start=1)]
            debug.setdefault("comet_attempts", []).append({"route": "openai-compatible-edits", "model": model, "field": field, "variant": variant})
            try:
                response = await client.post(base + (path if path.startswith("/") else "/" + path), headers=headers, data=data, files=files)
                try:
                    payload: Any = response.json()
                except Exception:
                    payload = {"raw": response.text[:1200]}
                if response.status_code >= 400:
                    message = f"{model}/{field} HTTP {response.status_code}: {str(payload)[:700]}"
                    errors.append(message)
                    if response.status_code in {401, 403} or v150._looks_auth_error(message):
                        _AUTH_DISABLED["comet"] = message[:500]
                        raise v139.PipelineError("auth_or_key", message, debug=debug)
                    continue
                raw = _image_from_payload(payload)
                if not raw:
                    value = _image_url(payload)
                    if value:
                        downloaded = await client.get(value, headers={"Accept": "image/*,*/*"})
                        if downloaded.status_code < 400 and downloaded.content:
                            raw = downloaded.content
                if raw:
                    return _normalise_output(raw, aspect)
                errors.append(f"{model}/{field}: response contained no image")
            except v139.PipelineError:
                raise
            except Exception as exc:
                errors.append(f"{model}/{field}: {_safe_error(exc)}")
    raise RuntimeError("Comet OpenAI-compatible edit failed: " + " | ".join(errors[-4:])[:1600])


def _candidate_problem(raw: bytes) -> str:
    try:
        metrics = _image_metrics(raw)
        if metrics["short_side"] < 700:
            return "resolution too small"
        if metrics["brightness"] < 18 or metrics["brightness"] > 242:
            return "exposure unusable"
        if metrics["contrast"] < 8:
            return "contrast unusable"
        boxes = _face_boxes(raw)
        if boxes and len(boxes) != 2:
            return f"expected two main faces, detector found {len(boxes)}"
        return ""
    except Exception as exc:
        return f"invalid image: {_safe_error(exc)}"


def _qc_board(user_ref: bytes, celebrity_ref: bytes, candidate: bytes) -> bytes:
    ref_size = 620
    cand_w, cand_h = 900, 1125
    board = Image.new("RGB", (ref_size * 2 + cand_w, max(ref_size, cand_h)), (22, 22, 22))
    user = ImageOps.fit(_open_rgb(_face_crop(user_ref, ref_size)), (ref_size, ref_size), method=Image.Resampling.LANCZOS)
    celebrity = ImageOps.fit(_open_rgb(_face_crop(celebrity_ref, ref_size)), (ref_size, ref_size), method=Image.Resampling.LANCZOS)
    result = ImageOps.fit(_open_rgb(candidate), (cand_w, cand_h), method=Image.Resampling.LANCZOS)
    board.paste(user, (0, 0))
    board.paste(celebrity, (ref_size, 0))
    board.paste(result, (ref_size * 2, 0))
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default()
    for x, text in ((12, "USER REF"), (ref_size + 12, "PUBLIC REF"), (ref_size * 2 + 12, "CANDIDATE")):
        draw.rounded_rectangle((x, 12, x + 126, 54), radius=9, fill=(0, 0, 0))
        draw.text((x + 12, 24), text, fill=(255, 255, 255), font=font)
    return _encode_jpeg(board, 93)


async def _candidate_qc(
    mod: Any,
    raw: bytes,
    user_ref: bytes,
    celebrity_ref: bytes,
    scene: str,
    debug: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    local_problem = _candidate_problem(raw)
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision) or not _flag("CELEBRITY_V156_VISION_QC", True):
        return {
            "accepted": not local_problem,
            "unknown": True,
            "user_similarity": 0.0,
            "celebrity_similarity": 0.0,
            "quality": 55.0 if not local_problem else 0.0,
            "reason": local_problem or "vision-qc-unavailable",
        }
    prompt = (
        "QC board: LEFT panel is USER identity reference, MIDDLE is PUBLIC FIGURE identity reference, RIGHT is a fictional generated two-person photo. Do not identify or name anyone. "
        "Compare the left person in CANDIDATE only to USER REF and the right person only to PUBLIC REF. Return strict JSON only with: "
        "user_similarity integer 0-100, celebrity_similarity integer 0-100, exactly_two_main_adults boolean, user_on_left boolean, celebrity_on_right boolean, separate_identities boolean, real_living_people_not_wax boolean, no_plaque_poster_or_museum_display boolean, one_seamless_scene boolean, scene_match boolean, attire_match boolean, face_quality integer 0-100, overall_quality integer 0-100, reason short string. "
        "Reject wax/statue/mannequin/exhibit, copied source surroundings or clothes, plaques, text boards, split screens, pasted rectangles, extra prominent people, blended identities, wrong sides, implausible scale, severe face deformation or scene/clothing mismatch. "
        f"Requested scene: {scene[:900]}"
    )
    try:
        board = _qc_board(user_ref, celebrity_ref, raw)
        answer = await vision(prompt, base64.b64encode(board).decode("ascii"), "image/jpeg")
        data = _json_object(answer)
        user_score = max(0.0, min(100.0, float(data.get("user_similarity") or 0)))
        celebrity_score = max(0.0, min(100.0, float(data.get("celebrity_similarity") or 0)))
        face_quality = max(0.0, min(100.0, float(data.get("face_quality") or 0)))
        overall = max(0.0, min(100.0, float(data.get("overall_quality") or 0)))
        structural = all(data.get(key) is not False for key in (
            "exactly_two_main_adults",
            "user_on_left",
            "celebrity_on_right",
            "separate_identities",
            "real_living_people_not_wax",
            "no_plaque_poster_or_museum_display",
            "one_seamless_scene",
            "scene_match",
        ))
        min_user = _number("CELEBRITY_V156_MIN_USER_SIMILARITY", 64, 40, 92)
        min_celebrity = _number("CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY", 62, 40, 92)
        min_quality = _number("CELEBRITY_V156_MIN_QUALITY", 66, 40, 92)
        accepted = not local_problem and structural and user_score >= min_user and celebrity_score >= min_celebrity and min(face_quality, overall) >= min_quality
        total = user_score * 0.34 + celebrity_score * 0.38 + face_quality * 0.12 + overall * 0.16
        result = {
            "label": label,
            "accepted": accepted,
            "unknown": False,
            "user_similarity": round(user_score, 1),
            "celebrity_similarity": round(celebrity_score, 1),
            "identity_min": round(min(user_score, celebrity_score), 1),
            "face_quality": round(face_quality, 1),
            "quality": round(overall, 1),
            "total": round(total, 2),
            "reason": str(data.get("reason") or local_problem or "ok")[:420],
            "checks": {key: data.get(key) for key in (
                "exactly_two_main_adults", "user_on_left", "celebrity_on_right", "separate_identities",
                "real_living_people_not_wax", "no_plaque_poster_or_museum_display", "one_seamless_scene",
                "scene_match", "attire_match",
            )},
        }
        debug.setdefault("candidate_qc", []).append(result)
        return result
    except Exception as exc:
        debug.setdefault("qc_errors", []).append(f"{label}:{_safe_error(exc)}")
        return {
            "label": label,
            "accepted": False,
            "unknown": True,
            "user_similarity": 0.0,
            "celebrity_similarity": 0.0,
            "identity_min": 0.0,
            "quality": 0.0,
            "total": 0.0,
            "reason": f"vision-qc-error:{_safe_error(exc)}"[:420],
        }


def _repair_prompt(side: str, celebrity_name: str, scene: str) -> str:
    target = "LEFT USER" if side == "user" else f"RIGHT PUBLIC FIGURE ({celebrity_name})"
    preserve = "RIGHT public figure" if side == "user" else "LEFT user"
    return (
        f"Edit the supplied CURRENT DRAFT. Repair only the facial identity and natural head geometry of {target} using the matching identity references. "
        f"Keep the {preserve} unchanged. Preserve the exact scene, camera angle, body positions, clothing, hands, lighting, background and composition. "
        "Do not copy any reference background, clothing, plaque, glass reflection, museum display or text. Keep exactly two living adults, user left and public figure right. "
        "No wax figure, statue, mannequin, exhibit, poster, collage, added people, side swap, blended identity, beautification or age change. "
        f"Requested scene remains: {_scene_profile(scene)}. {_attire_contract(scene)} Return only the complete edited photograph."
    )


async def _render_candidate(
    mod: Any,
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    aspect: str,
    debug: dict[str, Any],
    variant: int,
) -> tuple[bytes, str]:
    prompt = _scene_prompt(celebrity_name, scene, aspect, variant)
    routes_raw = os.environ.get("CELEBRITY_V156_COMET_ROUTES") or "gemini,openai-edit"
    routes = [item.strip().casefold() for item in routes_raw.split(",") if item.strip()]
    errors: list[str] = []
    for route in routes:
        try:
            if route == "gemini":
                return await _comet_gemini_render(mod, user_refs, celebrity_refs, prompt, aspect, debug, variant), "comet-gemini"
            if route in {"openai", "openai-edit", "gpt-image"}:
                return await _comet_openai_edit_render(mod, user_refs, celebrity_refs, prompt, aspect, debug, variant), "comet-openai-edit"
        except v139.PipelineError:
            raise
        except Exception as exc:
            errors.append(f"{route}:{_safe_error(exc)}")
    raise RuntimeError("No Comet render route succeeded: " + " | ".join(errors[-4:])[:1700])


async def _repair_candidate(
    mod: Any,
    raw: bytes,
    qc: dict[str, Any],
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    aspect: str,
    debug: dict[str, Any],
    variant: int,
) -> bytes | None:
    user_score = float(qc.get("user_similarity") or 0)
    celebrity_score = float(qc.get("celebrity_similarity") or 0)
    min_user = _number("CELEBRITY_V156_MIN_USER_SIMILARITY", 64, 40, 92)
    min_celeb = _number("CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY", 62, 40, 92)
    if user_score >= min_user and celebrity_score >= min_celeb:
        return None
    side = "user" if user_score <= celebrity_score else "celebrity"
    stage = v139._stage_start(debug, f"v156_repair_{side}_{variant}", "comet-gemini", side=side)
    try:
        output = await _comet_gemini_render(
            mod,
            user_refs,
            celebrity_refs,
            _repair_prompt(side, celebrity_name, scene),
            aspect,
            debug,
            variant,
            draft=raw,
            repair_side=side,
        )
        v139._stage_finish(stage, "ok", bytes=len(output), side=side)
        return output
    except Exception as exc:
        v139._record_error(debug, stage, exc)
        return None


async def _run_v156_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    del previous_result
    global _LAST_RUN_DEBUG
    if not user_photo:
        raise v139.PipelineError("input", "User selfie is missing")
    if not celebrity_refs:
        raise v139.PipelineError("input", "Public-person references are missing")
    if not _comet_key(mod):
        raise v139.PipelineError("auth_or_key", "COMET_API_KEY missing")

    async with _generation_gate():
        aspect = v139.selfie._aspect_for_scene(scene)
        debug = v139._new_debug(celebrity_name, scene, aspect)
        debug.update({
            "version": VERSION,
            "architecture": "comet_dual_identity_best_of_n+targeted_weak_side_repair+vision_qc",
            "providers": ["comet-gemini", "comet-openai-edit"],
            "direct_gemini": False,
            "direct_openai_images": False,
            "photoroom_composite": False,
            "local_rembg": False,
            "piapi": False,
            "face_swap": False,
            "user_pixel_preserved": False,
            "user_face_regenerated": True,
            "identity_candidates": [],
            "candidate_qc": [],
            "repair_candidates": [],
            "comet_attempts": [],
            "rss_before_mb": round(_rss_mb(), 1),
        })
        try:
            user_refs = [user_photo] + [raw for raw in (additional_user_refs or []) if raw]
            user_refs = user_refs[:2]
            public_refs = await _rank_celebrity_references(mod, celebrity_refs, debug)
            debug["selected_reference_count"] = len(public_refs)
            count = _integer("CELEBRITY_V156_CANDIDATES", 3, 2, 4)
            accepted: list[dict[str, Any]] = []
            repair_pool: list[tuple[bytes, dict[str, Any], int, str]] = []

            for variant in range(count):
                label = f"v156_candidate_{variant + 1}"
                stage = v139._stage_start(debug, label, "comet", variant=variant)
                try:
                    raw, provider = await _render_candidate(
                        mod, user_refs, public_refs, celebrity_name, scene, aspect, debug, variant
                    )
                    problem = _candidate_problem(raw)
                    if problem:
                        raise v139.PipelineError("structural_qc", problem, debug=debug)
                    qc = await _candidate_qc(mod, raw, user_refs[0], public_refs[0], scene, debug, label)
                    row = {
                        "label": label,
                        "provider": provider,
                        "output": raw,
                        "user_identity": float(qc.get("user_similarity") or 0),
                        "celebrity_identity": float(qc.get("celebrity_similarity") or 0),
                        "identity_min": float(qc.get("identity_min") or 0),
                        "identity_unknown": bool(qc.get("unknown")),
                        "quality": float(qc.get("quality") or 0),
                        "total": float(qc.get("total") or 0),
                        "reason": qc.get("reason"),
                        "user_pixel_preserved": False,
                        "user_face_regenerated": True,
                    }
                    debug["identity_candidates"].append({k: v for k, v in row.items() if k != "output"})
                    if qc.get("accepted"):
                        accepted.append(row)
                        v139._stage_finish(stage, "ok", total=row["total"], user=row["user_identity"], celebrity=row["celebrity_identity"], bytes=len(raw))
                        if row["total"] >= _number("CELEBRITY_V156_EARLY_ACCEPT_TOTAL", 82, 65, 96):
                            break
                    else:
                        repair_pool.append((raw, qc, variant, provider))
                        v139._stage_finish(stage, "rejected", total=row["total"], reason=str(qc.get("reason") or "")[:240])
                except Exception as exc:
                    v139._record_error(debug, stage, exc)

            if not accepted and _flag("CELEBRITY_V156_TARGETED_REPAIR", True):
                repair_pool.sort(key=lambda item: float(item[1].get("total") or 0), reverse=True)
                for raw, qc, variant, provider in repair_pool[:2]:
                    repaired = await _repair_candidate(
                        mod, raw, qc, user_refs, public_refs, celebrity_name, scene, aspect, debug, variant
                    )
                    if not repaired:
                        continue
                    label = f"v156_repaired_{variant + 1}"
                    repaired_qc = await _candidate_qc(mod, repaired, user_refs[0], public_refs[0], scene, debug, label)
                    row = {
                        "label": label,
                        "provider": provider + "+comet-targeted-repair",
                        "output": repaired,
                        "user_identity": float(repaired_qc.get("user_similarity") or 0),
                        "celebrity_identity": float(repaired_qc.get("celebrity_similarity") or 0),
                        "identity_min": float(repaired_qc.get("identity_min") or 0),
                        "identity_unknown": bool(repaired_qc.get("unknown")),
                        "quality": float(repaired_qc.get("quality") or 0),
                        "total": float(repaired_qc.get("total") or 0),
                        "reason": repaired_qc.get("reason"),
                        "user_pixel_preserved": False,
                        "user_face_regenerated": True,
                    }
                    debug["repair_candidates"].append({k: v for k, v in row.items() if k != "output"})
                    if repaired_qc.get("accepted"):
                        accepted.append(row)

            if not accepted:
                raise v139.PipelineError(
                    "identity_pipeline",
                    "No candidate passed dual-identity, scene and anti-wax quality control",
                    debug=debug,
                )
            accepted.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
            best = accepted[0]
            debug["selected"] = {k: v for k, v in best.items() if k != "output"}
            debug["failure_class"] = None
            debug["finished_at"] = time.time()
            debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
            debug["rss_after_mb"] = round(_rss_mb(), 1)
            public = v139._public_debug(debug)
            for key in (
                "architecture", "providers", "selected_reference_count", "reference_local_ranking",
                "reference_vision_qc", "candidate_qc", "identity_candidates", "repair_candidates",
                "comet_attempts", "selected", "rss_before_mb", "rss_after_mb",
            ):
                if key in debug:
                    public[key] = debug[key]
            _LAST_RUN_DEBUG = public
            v139._LAST_RUN_DEBUG = public
            return best["output"], public
        except Exception as exc:
            category = getattr(exc, "category", None) or v139._classify_error(exc)
            debug["failure_class"] = category
            debug["finished_at"] = time.time()
            debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
            debug["rss_after_mb"] = round(_rss_mb(), 1)
            public = v139._public_debug(debug)
            for key in (
                "architecture", "providers", "reference_local_ranking", "reference_vision_qc",
                "candidate_qc", "identity_candidates", "repair_candidates", "comet_attempts",
                "rss_before_mb", "rss_after_mb",
            ):
                if key in debug:
                    public[key] = debug[key]
            _LAST_RUN_DEBUG = public
            v139._LAST_RUN_DEBUG = public
            if isinstance(exc, v139.PipelineError):
                exc.debug = public
                raise
            raise v139.PipelineError(category, _safe_error(exc), debug=public) from exc
        finally:
            gc.collect()


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
    output, _ = await _run_v156_generation(
        mod, user_photo, celebrity_refs, celebrity_name, scene,
        previous_result=previous_result, additional_user_refs=additional_user_refs,
    )
    return output


def _result_kb(has_selected: bool):
    del has_selected
    return v139.selfie.engine._kb([
        [("🔁 Повторить эту же сцену", "celeb:retry_scene")],
        [("🎬 Премьера", "celeb:preset:redcarpet"), ("🍽 Ресторан", "celeb:preset:restaurant")],
        [("⛵ Яхта", "celeb:preset:yacht"), ("🏛 Выставка", "celeb:preset:exhibition")],
        [("🏙 Красная площадь", "celeb:preset:red_square")],
        [("⭐ Сменить знаменитость", "celeb:menu"), ("✅ Готово", "celeb:cancel")],
    ])


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    del refinement
    engine = v139.selfie.engine
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
            f"⏳ Создаю несколько цельных вариантов с {celebrity_name}, отдельно проверяю оба лица, сцену и одежду. "
            "Музейные фигуры, таблички, коллажи и плохие склейки будут отброшены. Обычно 3–8 минут."
        )
        try:
            output, debug = await _run_v156_generation(
                mod, user_photo, refs, celebrity_name, scene,
                additional_user_refs=[second_user] if second_user else [],
            )
        except Exception as exc:
            debug = getattr(exc, "debug", None) or _LAST_RUN_DEBUG or {}
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "await_scene"
                session["v139_debug"] = debug if isinstance(debug, dict) else {}
                session["v156_debug"] = debug if isinstance(debug, dict) else {}
                session["last_generation_error"] = _safe_error(exc)
                session["last_generation_failed_at"] = time.time()
                session["generation_failures"] = int(session.get("generation_failures") or 0) + 1
                session.pop("generation_id", None)
                run_id = str((debug or {}).get("run_id") or "-")
                await update.effective_message.reply_text(
                    "❌ Качественный результат не получен, поэтому изображение не отправлено. "
                    + v139._failure_message(exc, debug or {})
                    + f"\nКод диагностики: {run_id}. Кредиты за невыданный результат не должны списываться.",
                    reply_markup=v139.selfie.v133._failure_kb(),
                )
            return False
        if not v139.selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            session.pop("generation_id", None)
            return False
        selected = debug.get("selected") or {}
        identity_min = float(selected.get("identity_min") or 0)
        session["v139_debug"] = debug
        session["v156_debug"] = debug
        session["delivery_mode"] = "verified"
        session["delivery_identity_min"] = identity_min
        session["result_path"] = engine._store_image(session, "result_v156.jpg", output)
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session["generation_failures"] = 0
        session.pop("generation_id", None)
        from telegram import InputFile
        bio = BytesIO(output)
        bio.name = "celebrity_selfie.jpg"
        caption = (
            "📸 AI-селфи готово ✅\n"
            f"Персона: {celebrity_name}\n"
            f"Раздельная оценка двух лиц: минимум {identity_min:.0f}/100.\n"
            "Кадр создан целиком по вашим референсам; сцена, одежда и оба человека прошли проверку качества.\n"
            "Пометка: изображение создано ИИ и не подтверждает реальную встречу, поддержку или партнёрство."
        )
        markup = _result_kb(bool(engine._selected_entry(session)))
        if engine._flag("CELEBRITY_SELFIE_SEND_AS_DOCUMENT", True):
            await update.effective_message.reply_document(InputFile(bio), caption=caption[:1024], reply_markup=markup)
        else:
            await update.effective_message.reply_photo(photo=output, caption=caption[:1024], reply_markup=markup)
        return True

    pay = getattr(mod, "_try_pay_then_do", None)
    if not callable(pay):
        await work()
        return
    cost = float(os.environ.get("CELEBRITY_V156_UNIT_COST_USD") or os.environ.get("CELEBRITY_V139_UNIT_COST_USD") or 0.80)
    await pay(
        update, context, update.effective_user.id, "img", cost, work,
        remember_kind="celebrity_selfie_v156",
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "generation_id": generation_id,
            "pipeline": VERSION,
            "architecture": "comet-dual-identity-best-of-n",
            "candidate_count": _integer("CELEBRITY_V156_CANDIDATES", 3, 2, 4),
            "user_references": 2 if second_user else 1,
        },
    )


async def _on_callback(update: Any, context: Any) -> None:
    data = str(getattr(getattr(update, "callback_query", None), "data", "") or "")
    if data == "celeb:retry_scene":
        with contextlib.suppress(Exception):
            await update.callback_query.answer()
        await _generate(update, context)
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop
    await _ORIGINAL_CALLBACK(update, context)


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
    debug = session.get("v156_debug") or session.get("v139_debug") or _LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    mod = v139.selfie.engine._runtime_module()
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=comet_dual_identity_best_of_n+targeted_weak_side_repair+vision_qc",
        "scene_and_both_people=single_coherent_generation",
        "celebrity_source_cutout=disabled",
        "user_source_cutout=disabled",
        "photoroom_composite=disabled",
        "local_rembg=disabled",
        "direct_gemini=disabled",
        "direct_openai_images=disabled",
        "piapi=disabled",
        "face_swap=disabled",
        "anti_wax_plaque_exhibit_gate=required",
        f"comet={'ready' if bool(_comet_key(mod)) else 'missing'}",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"selected_references={debug.get('selected_reference_count') or 0}",
        f"candidates={len(debug.get('identity_candidates') or [])}",
        f"repairs={len(debug.get('repair_candidates') or [])}",
        f"user_similarity={selected.get('user_identity', '-')}",
        f"celebrity_similarity={selected.get('celebrity_identity', '-')}",
        f"quality={selected.get('quality', '-')}",
        f"rss_before_mb={debug.get('rss_before_mb', '-')}",
        f"rss_after_mb={debug.get('rss_after_mb', '-')}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    for item in (debug.get("errors") or [])[-6:]:
        lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:320]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    if getattr(v139.selfie.engine, _INSTALL_FLAG, False):
        _patch_version_contract()
        return
    os.environ["CELEBRITY_V142_LOCAL_REMBG_FALLBACK"] = "0"
    os.environ["CELEBRITY_V142_LEGACY_FALLBACK"] = "0"
    os.environ["CELEBRITY_V141_OPENAI_QUALITY_CLEANUP"] = "0"
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"
    os.environ.setdefault("CELEBRITY_V156_UNIT_COST_USD", "0.80")
    os.environ.setdefault("CELEBRITY_V156_CANDIDATES", "3")
    os.environ.setdefault("CELEBRITY_V156_COMET_ROUTES", "gemini,openai-edit")
    os.environ.setdefault("CELEBRITY_V156_TARGETED_REPAIR", "1")
    os.environ.setdefault("CELEBRITY_V156_MAX_CONCURRENCY", "1")
    os.environ.setdefault("CELEBRITY_V156_MIN_USER_SIMILARITY", "64")
    os.environ.setdefault("CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY", "62")
    os.environ.setdefault("CELEBRITY_V156_MIN_QUALITY", "66")

    v139.install_runtime_patches()
    v139.VERSION = VERSION
    v139._run_two_stage_generation = _run_v156_generation
    v139._generate = _generate
    v139.selfie._run_v156_generation = _run_v156_generation
    v139.selfie._run_v139_generation = _run_v156_generation
    v139.selfie._generate = _generate
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._generate = _generate
    v139.selfie.engine._result_kb = _result_kb
    v139.selfie.engine._on_callback = _on_callback
    v139.selfie.engine._diag = _diag
    setattr(v139.selfie.engine, _INSTALL_FLAG, True)
    _patch_version_contract()
    log.info("installed %s comet=%s old_media_paths=disabled", VERSION, bool(_comet_key()))


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    # Register the audited wizard/callback handlers first, then wrap the resulting
    # builder so v156 remains the final generation and diagnostics owner.
    v139.install_builder_hook()
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        install()
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            for command in ("diag_selfie_v156", "diag_selfie_v155", "diag_selfie_v154", "diag_celebrity_flow", "diag_brand"):
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
    "_rank_celebrity_references", "_scene_prompt", "_comet_gemini_render",
    "_comet_openai_edit_render", "_candidate_qc", "_run_v156_generation",
    "_generate", "_diag",
]
