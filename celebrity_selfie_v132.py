# -*- coding: utf-8 -*-
"""Celebrity Selfie v132: strict production scene/output pipeline.

v131 fixed false rejection of ordinary user portraits. v132 fixes the next
failure mode seen in production: a provider could return a technical reference
sheet or split-screen image and the old generic response parser could treat it
as a finished selfie. This release creates a fresh scene from face-only crops,
extracts only PiAPI's explicit output fields, validates every intermediate and
final image, retries transient failures, and never publishes a draft/composite.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import time
import uuid
from io import BytesIO
from typing import Any, Iterable

import httpx
from PIL import Image, ImageChops, ImageOps, ImageStat

import celebrity_selfie_v131 as previous

impl = previous.impl
core = impl.core
engine = impl.engine

VERSION = "v132-celebrity-selfie-validated-final-output-2026-07-19"
log = logging.getLogger("gpt-bot.celebrity-selfie-v132")

# Keep the complete reused routing chain on one owner/version identifier.
for _module in (
    previous,
    previous.previous,
    impl,
    impl.previous,
    impl.previous.previous,
    impl.previous.previous.previous,
    impl.previous.previous.previous.previous,
    core,
):
    with contextlib.suppress(Exception):
        _module.VERSION = VERSION


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


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int = 95) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _face_boxes(raw: bytes) -> list[dict[str, Any]]:
    detector = impl._runtime_detector()
    if not callable(detector):
        return []
    try:
        result = detector(raw)
        return [dict(item) for item in (result or []) if isinstance(item, dict)]
    except Exception as exc:
        log.info("Face boxes unavailable: %s", exc)
        return []


def _face_crop(raw: bytes, size: int = 896) -> bytes:
    """Create a large, single-identity crop instead of sending a whole scene.

    Passing full environmental portraits to an image-edit model caused it to
    reproduce the source background or place the source next to the requested
    scene. Face-only crops remove that ambiguity and improve PiAPI source order.
    """
    image = _open_rgb(raw)
    boxes = _face_boxes(raw)
    if boxes:
        face = max(boxes, key=lambda item: float(item.get("area") or 0))
        x = float(face.get("x") or 0)
        y = float(face.get("y") or 0)
        w = max(1.0, float(face.get("w") or 1))
        h = max(1.0, float(face.get("h") or 1))
        cx = x + w / 2.0
        cy = y + h / 2.0
        side = max(w, h) * 2.65
        # Include hair/chin but avoid most of the environmental background.
        cy -= h * 0.08
        left = max(0, int(round(cx - side / 2)))
        top = max(0, int(round(cy - side / 2)))
        right = min(image.width, int(round(cx + side / 2)))
        bottom = min(image.height, int(round(cy + side / 2)))
        if right - left >= 64 and bottom - top >= 64:
            image = image.crop((left, top, right, bottom))
    else:
        # Detector misses are common on ordinary portraits; use a conservative
        # upper-centre crop rather than rejecting the source.
        image = ImageOps.fit(
            image,
            (min(image.width, image.height), min(image.width, image.height)),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.34),
        )
    image = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    return _encode_jpeg(image, quality=96)


def _source_pair(user_photo: bytes, celebrity_ref: bytes) -> bytes:
    left = _open_rgb(_face_crop(user_photo, 896))
    right = _open_rgb(_face_crop(celebrity_ref, 896))
    sheet = Image.new("RGB", (1792, 896), (32, 32, 32))
    sheet.paste(left, (0, 0))
    sheet.paste(right, (896, 0))
    return _encode_jpeg(sheet, quality=96)


def _seam_metrics(raw: bytes) -> dict[str, float]:
    image = _open_rgb(raw)
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    width, height = image.size
    if width < 32 or height < 32:
        return {"ratio": 1.0, "center_jump": 0.0, "typical_jump": 0.0, "seam_ratio": 0.0}
    # PIL-only column difference avoids a hard dependency on NumPy in tests.
    jumps: list[float] = []
    for x in range(1, width):
        a = image.crop((x - 1, 0, x, height))
        b = image.crop((x, 0, x + 1, height))
        diff = ImageChops.difference(a, b)
        jumps.append(float(sum(ImageStat.Stat(diff).mean) / 3.0))
    ordered = sorted(jumps)
    typical = ordered[len(ordered) // 2] if ordered else 0.0
    centre = width // 2
    band = max(1, int(width * 0.025))
    start = max(0, centre - band - 1)
    end = min(len(jumps), centre + band)
    centre_jump = max(jumps[start:end] or [0.0])
    return {
        "ratio": width / float(max(1, height)),
        "center_jump": centre_jump,
        "typical_jump": typical,
        "seam_ratio": centre_jump / max(1.0, typical),
    }


def _thumb(raw: bytes, size: tuple[int, int] = (48, 48)) -> Image.Image:
    return ImageOps.fit(_open_rgb(raw).convert("L"), size, method=Image.Resampling.LANCZOS)


def _visual_similarity(raw_a: bytes, raw_b: bytes) -> float:
    """Return a coarse 0..1 similarity used only to detect leaked inputs."""
    try:
        a = _thumb(raw_a)
        b = _thumb(raw_b)
        diff = ImageChops.difference(a, b)
        mean = float(ImageStat.Stat(diff).mean[0])
        return max(0.0, min(1.0, 1.0 - mean / 255.0))
    except Exception:
        return 0.0


def _half_similarity(raw: bytes, reference: bytes, left: bool) -> float:
    try:
        image = _open_rgb(raw)
        mid = image.width // 2
        half = image.crop((0, 0, mid, image.height) if left else (mid, 0, image.width, image.height))
        return _visual_similarity(_encode_jpeg(half, 92), reference)
    except Exception:
        return 0.0


def _image_problem(
    raw: bytes,
    *,
    stage: str,
    user_photo: bytes | None = None,
    source_pair: bytes | None = None,
    require_two_faces: bool = False,
) -> str:
    try:
        image = _open_rgb(raw)
    except Exception:
        return "провайдер вернул повреждённый файл"
    width, height = image.size
    if min(width, height) < 480:
        return f"слишком низкое разрешение {width}×{height}"
    ratio = width / float(max(1, height))
    if ratio > 1.92 or ratio < 0.50:
        return f"неподходящее соотношение сторон {ratio:.2f}"
    seam = _seam_metrics(raw)
    if seam["ratio"] > 1.55 and seam["center_jump"] >= 25.0 and seam["seam_ratio"] >= 3.6:
        return "обнаружена техническая склейка или split-screen"
    if source_pair and _visual_similarity(raw, source_pair) >= 0.91:
        return "вместо результата возвращён лист исходных референсов"
    if user_photo and ratio > 1.45:
        left_sim = _half_similarity(raw, user_photo, True)
        right_sim = _half_similarity(raw, user_photo, False)
        if max(left_sim, right_sim) >= 0.91 and seam["seam_ratio"] >= 2.8:
            return "в итог попало исходное фото рядом с другой картинкой"
    if require_two_faces:
        boxes = _face_boxes(raw)
        if boxes and len(boxes) < 2:
            return f"в {stage} найдено только одно уверенное лицо"
        if len(boxes) > 3:
            return f"в {stage} найдено слишком много крупных лиц"
    return ""


def _explicit_output_object(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict) and data.get("output") is not None:
        return data.get("output")
    return payload.get("output")


def _output_candidates(output: Any) -> Iterable[tuple[str, str]]:
    if isinstance(output, str):
        yield "auto", output
        return
    if isinstance(output, (list, tuple)):
        for item in output:
            yield from _output_candidates(item)
        return
    if not isinstance(output, dict):
        return
    for key in ("image_url", "imageUrl", "url", "download_url"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            yield "url", value.strip()
    for key in ("image_base64", "image_b64", "b64_json", "base64", "image"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            yield "base64", value.strip()
    for key in ("images", "urls", "result"):
        if key in output:
            yield from _output_candidates(output[key])


async def _extract_piapi_output(payload: Any, client: httpx.AsyncClient) -> bytes | None:
    """Read only data.output/output; never recurse into provider input/config."""
    output = _explicit_output_object(payload)
    if output is None:
        return None
    for kind, value in _output_candidates(output):
        if kind in {"url", "auto"} and value.startswith(("https://", "http://")):
            try:
                response = await client.get(value, headers={"Accept": "image/*"})
                if response.status_code < 400 and response.content:
                    return bytes(response.content)
            except Exception:
                continue
        if value.startswith("data:image") and "," in value:
            value = value.split(",", 1)[1]
        if kind in {"base64", "auto"} and len(value) > 200:
            with contextlib.suppress(Exception):
                raw = base64.b64decode(value, validate=False)
                if raw:
                    return raw
    return None


def _task_id(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            value = data.get("task_id") or data.get("id")
            if value:
                return str(value)
        value = payload.get("task_id") or payload.get("id")
        if value:
            return str(value)
    return ""


def _task_status(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("status") or data.get("state") or "").casefold()
        return str(payload.get("status") or payload.get("state") or "").casefold()
    return ""


def _provider_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:500]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("raw_message") or error.get("detail") or "")[:500]
    return str(data.get("detail") or payload.get("message") or "")[:500]


async def _piapi_task(mod: Any, task_type: str, inputs: dict[str, Any]) -> bytes:
    key = impl._piapi_key(mod)
    if not key:
        raise RuntimeError("PIAPI_API_KEY отсутствует")
    base_url = str(getattr(mod, "PIAPI_BASE_URL", "") or os.environ.get("PIAPI_BASE_URL") or "https://api.piapi.ai").rstrip("/")
    create_path = str(getattr(mod, "PIAPI_FACE_CREATE_PATH", "") or os.environ.get("PIAPI_FACE_CREATE_PATH") or "/api/v1/task")
    status_path = str(getattr(mod, "PIAPI_FACE_STATUS_PATH", "") or os.environ.get("PIAPI_FACE_STATUS_PATH") or "/api/v1/task/{task_id}")
    model = str(getattr(mod, "PIAPI_FACE_MODEL", "") or os.environ.get("PIAPI_FACE_MODEL") or "Qubico/image-toolkit")
    timeout_s = _number("CELEBRITY_IDENTITY_TIMEOUT_S", 360, 90, 900)
    poll_s = _number("CELEBRITY_IDENTITY_POLL_S", 2.5, 1, 15)
    deadline = time.monotonic() + timeout_s
    headers = {
        "x-api-key": key,
        "X-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "model": model,
        "task_type": task_type,
        "input": inputs,
        "config": {"webhook_config": {"endpoint": "", "secret": ""}},
    }
    last_http = ""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=35, read=90, write=180),
        follow_redirects=True,
    ) as client:
        response = None
        for create_attempt in range(3):
            response = await client.post(base_url + create_path, headers=headers, json=body)
            if response.status_code < 400:
                break
            last_http = f"HTTP {response.status_code}: {response.text[:350]}"
            if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                break
            await asyncio.sleep(1.5 * (create_attempt + 1))
        if response is None or response.status_code >= 400:
            raise RuntimeError("PiAPI create failed: " + last_http)
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"PiAPI create returned invalid JSON: {exc}") from exc
        direct = await _extract_piapi_output(payload, client)
        if direct:
            return impl._jpeg(direct, max_side=1900, quality=96)
        task_id = _task_id(payload)
        if not task_id:
            raise RuntimeError("PiAPI не вернул task_id")
        status_url = base_url + status_path.replace("{task_id}", task_id)
        transient_errors = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_s)
            try:
                status_response = await client.get(status_url, headers=headers)
            except Exception as exc:
                transient_errors += 1
                if transient_errors <= 4:
                    continue
                raise RuntimeError(f"PiAPI status network error: {exc}") from exc
            if status_response.status_code >= 400:
                transient_errors += 1
                if status_response.status_code in {408, 425, 429, 500, 502, 503, 504} and transient_errors <= 5:
                    continue
                raise RuntimeError(f"PiAPI status HTTP {status_response.status_code}: {status_response.text[:350]}")
            try:
                payload = status_response.json()
            except Exception:
                continue
            raw = await _extract_piapi_output(payload, client)
            if raw:
                return impl._jpeg(raw, max_side=1900, quality=96)
            status = _task_status(payload)
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError("PiAPI task failed: " + (_provider_error(payload) or status))
        raise RuntimeError(f"PiAPI timeout after {timeout_s:.0f}s")


def _scene_prompt(celebrity_name: str, scene: str, variant: int) -> str:
    extra = (
        "Both people are shoulder-to-shoulder at the same depth and eye line."
        if variant == 0 else
        "The camera is held at arm's length; both heads are large, unobstructed and equally illuminated."
    )
    return (
        "Create ONE seamless, photorealistic smartphone selfie in a SINGLE continuous camera frame. "
        "This is not a collage, diptych, split-screen, before/after image, contact sheet or reference board. "
        "Exactly TWO foreground adults are together in the requested location: placeholder person A on the LEFT "
        f"and a placeholder with the approximate age/build of {celebrity_name} on the RIGHT. "
        "Both faces must be clearly visible, upright, similar in size and suitable for later face replacement. "
        "Do not paste or reproduce either reference image or its background. Use the reference crops only for broad "
        "age/hairstyle/body cues. No third foreground person, no text, logos, frames, borders or vertical divider. "
        f"{extra} Scene: {scene}. Natural skin, coherent lighting, realistic hands, casual fan selfie, portrait 4:5. "
        "Return only the finished image."
    )


def _gemini_image_from_json(payload: Any) -> bytes | None:
    if isinstance(payload, dict):
        inline = payload.get("inlineData") or payload.get("inline_data")
        if isinstance(inline, dict):
            value = inline.get("data") or inline.get("b64_json") or inline.get("base64")
            if isinstance(value, str) and len(value) > 200:
                with contextlib.suppress(Exception):
                    return base64.b64decode(value)
        for key in ("candidates", "content", "parts", "output", "response", "data", "result"):
            if key in payload:
                found = _gemini_image_from_json(payload[key])
                if found:
                    return found
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found = _gemini_image_from_json(item)
            if found:
                return found
    return None


async def _scene_draft(
    mod: Any,
    user_photo: bytes,
    celebrity_ref: bytes,
    celebrity_name: str,
    scene: str,
) -> bytes:
    api_key = str(getattr(mod, "COMET_API_KEY", "") or os.environ.get("COMET_API_KEY") or "")
    if not api_key:
        raise RuntimeError("COMET_API_KEY не задан")
    user_crop = _face_crop(user_photo, 768)
    celebrity_crop = _face_crop(celebrity_ref, 768)
    models: list[str] = []
    primary = str(getattr(mod, "COMET_IMAGE_EDIT_MODEL", "") or "").strip()
    if primary:
        models.append(primary)
    for value in list(getattr(mod, "COMET_IMAGE_EDIT_FALLBACK_MODELS", []) or []):
        value = str(value or "").strip()
        if value and value not in models:
            models.append(value)
    if not models:
        models = ["gemini-2.5-flash-image"]
    models = models[: int(_number("CELEBRITY_SCENE_MODEL_ATTEMPTS", 3, 1, 5))]
    base_url = str(getattr(mod, "COMET_BASE_URL", "https://api.cometapi.com") or "").rstrip("/")
    path_template = str(getattr(mod, "COMET_IMAGE_EDIT_PATH", "/v1beta/models/{model}:generateContent") or "/v1beta/models/{model}:generateContent")
    timeout_s = _number("CELEBRITY_SCENE_TIMEOUT_S", 600, 90, 900)
    errors: list[str] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180),
        follow_redirects=True,
    ) as client:
        for model in models:
            for variant in (0, 1):
                for camel in (True, False):
                    prompt = _scene_prompt(celebrity_name, scene, variant)
                    parts: list[dict[str, Any]] = [
                        {"text": prompt},
                        {"text": "REFERENCE A: cropped face/style cue for the LEFT placeholder; never reproduce its original background."},
                        engine._image_part(mod, user_crop, 768, camel),
                        {"text": "REFERENCE B: cropped face/style cue for the RIGHT placeholder; never reproduce its original background."},
                        engine._image_part(mod, celebrity_crop, 768, camel),
                    ]
                    config = {"responseModalities": ["TEXT", "IMAGE"]} if camel else {"response_modalities": ["TEXT", "IMAGE"]}
                    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
                    url = base_url + path_template.replace("{model}", model)
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    }
                    try:
                        response = await client.post(url, headers=headers, json=payload)
                        if response.status_code >= 400:
                            errors.append(f"scene {model} HTTP {response.status_code}: {response.text[:220]}")
                            continue
                        output = None
                        extractor = getattr(mod, "_image_bytes_from_response", None)
                        if callable(extractor):
                            output = await extractor(response, client)
                        if not output:
                            with contextlib.suppress(Exception):
                                output = _gemini_image_from_json(response.json())
                        if not output:
                            errors.append(f"scene {model}: empty image")
                            continue
                        output = impl._jpeg(output, max_side=1900, quality=95)
                        problem = _image_problem(
                            output,
                            stage="черновике сцены",
                            user_photo=user_photo,
                            require_two_faces=True,
                        )
                        if problem:
                            errors.append(f"scene {model}: {problem}")
                            continue
                        return output
                    except Exception as exc:
                        errors.append(f"scene {model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Не удалось собрать цельную сцену: " + " | ".join(errors[-5:])[:900])


async def _identity_lock(
    mod: Any,
    user_photo: bytes,
    celebrity_ref: bytes,
    target: bytes,
) -> bytes:
    source = _source_pair(user_photo, celebrity_ref)
    target = impl._jpeg(target, max_side=1900, quality=95)
    output = await _piapi_task(
        mod,
        "multi-face-swap",
        {
            "swap_image": impl._b64(source),
            "target_image": impl._b64(target),
            "swap_faces_index": "0,1",
            "target_faces_index": "0,1",
        },
    )
    problem = _image_problem(
        output,
        stage="финальном изображении",
        user_photo=user_photo,
        source_pair=source,
        require_two_faces=True,
    )
    if problem:
        raise RuntimeError("Финальная проверка отклонила результат: " + problem)
    return output


def _extract_json(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    with contextlib.suppress(Exception):
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        with contextlib.suppress(Exception):
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
    return None


async def _vision_qc(mod: Any, raw: bytes, scene: str) -> str:
    if not _flag("CELEBRITY_VISION_QC", True):
        return ""
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision):
        return ""
    prompt = (
        "Inspect only composition and location, not identity. Return strict JSON with keys: "
        "single_scene (boolean), split_screen (boolean), foreground_people (integer), "
        "scene_match (boolean), reason (short string). A valid result is one continuous smartphone photo, "
        "exactly two clear foreground people together, no collage/reference sheet/divider, and visually consistent "
        f"with this requested scene: {scene[:500]}"
    )
    try:
        answer = await vision(prompt, base64.b64encode(raw).decode("ascii"), "image/jpeg")
        data = _extract_json(answer)
        if not data:
            return ""
        if data.get("split_screen") is True or data.get("single_scene") is False:
            return "vision-QC обнаружил коллаж или несколько несвязанных кадров"
        people = data.get("foreground_people")
        if isinstance(people, (int, float)) and int(people) != 2:
            return f"vision-QC обнаружил {int(people)} людей вместо двух"
        if data.get("scene_match") is False:
            return "выбранная сцена не соответствует результату: " + str(data.get("reason") or "")[:260]
    except Exception as exc:
        log.info("Vision QC unavailable, local validation retained: %s", exc)
    return ""


async def _run_validated_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
) -> bytes:
    if not user_photo:
        raise RuntimeError("Исходное селфи пользователя отсутствует")
    best_ref = await impl._best_reference(celebrity_refs)
    rounds = int(_number("CELEBRITY_PIPELINE_ATTEMPTS", 2, 1, 4))
    errors: list[str] = []
    for attempt in range(rounds):
        try:
            # Refine keeps the accepted composition; initial generation creates a
            # new seamless scene from cropped identities, never from full photos.
            draft = previous_result or await _scene_draft(
                mod, user_photo, best_ref, celebrity_name, scene
            )
            draft_problem = _image_problem(
                draft,
                stage="черновике сцены",
                user_photo=user_photo,
                require_two_faces=not bool(previous_result),
            )
            if draft_problem:
                raise RuntimeError(draft_problem)
            output = await _identity_lock(mod, user_photo, best_ref, draft)
            qc_problem = await _vision_qc(mod, output, scene)
            if qc_problem:
                raise RuntimeError(qc_problem)
            return output
        except Exception as exc:
            errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            log.warning("Celebrity pipeline attempt %s/%s failed: %s", attempt + 1, rounds, exc)
            if previous_result:
                # Reapplying the same identities to the same accepted scene is
                # useful once more; no random scene regeneration is allowed.
                await asyncio.sleep(1.0)
    raise RuntimeError(
        "Ни один результат не прошёл финальную проверку; технический черновик не отправлен. "
        + " | ".join(errors[-rounds:])[:1100]
    )


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Запустите режим заново.")
        return
    now = time.monotonic()
    state = str(session.get("state") or "")
    started = float(session.get("generation_started_monotonic") or 0)
    if state in {"queued", "generating"} and now - started < 900:
        await update.effective_message.reply_text(
            "⏳ Генерация уже выполняется. Дождитесь результата; повторное нажатие не создаёт вторую платную задачу."
        )
        return

    user_photo = engine._read_path(session.get("user_photo_path"))
    ref_paths = engine._reference_paths(session)
    refs = [raw for raw in (engine._read_path(path) for path in ref_paths) if raw]
    if not user_photo:
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text("Пришлите своё селфи ещё раз.")
        return
    if not refs:
        session["state"] = "await_custom_refs"
        await update.effective_message.reply_text("Загрузите 1–4 фото знаменитости.")
        return
    scene = str(session.get("scene") or "").strip()
    if not scene:
        session["state"] = "await_scene"
        await update.effective_message.reply_text("Выберите или опишите сцену.", reply_markup=engine._scene_kb())
        return
    celebrity_name = str(session.get("celebrity_name") or "выбранный человек")
    previous_result = engine._read_path(session.get("result_path")) if refinement else None
    mod = engine._runtime_module()
    if mod is None:
        await update.effective_message.reply_text("Бот ещё загружается. Повторите через несколько секунд.")
        return

    generation_id = uuid.uuid4().hex
    session["generation_id"] = generation_id
    session["generation_started_monotonic"] = now
    session["generation_scene_snapshot"] = scene
    session["generation_celebrity_snapshot"] = celebrity_name
    session["state"] = "queued"

    async def work() -> bool:
        if session.get("generation_id") != generation_id:
            return False
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Повторно закрепляю оба исходных лица без изменения сцены…" if refinement else
            f"⏳ Создаю цельную сцену и затем отдельно закрепляю лица: {celebrity_name}. "
            "Черновики и коллажи пользователю не отправляются; ожидание обычно 2–6 минут."
        )
        try:
            output = await _run_validated_generation(
                mod,
                user_photo,
                refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
            )
        except Exception as exc:
            if session.get("generation_id") == generation_id:
                session["state"] = "result" if previous_result else "await_scene"
                session["last_generation_error"] = str(exc)[:1400]
                session["last_generation_failed_at"] = time.time()
                session.pop("generation_id", None)
                await update.effective_message.reply_text(
                    "❌ Результат не прошёл обязательную проверку и не был отправлен. "
                    "Оплата за повторное нажатие не должна создаваться.\n\nПричина: " + str(exc)[:850],
                    reply_markup=engine._result_kb(bool(engine._selected_entry(session))) if previous_result else engine._scene_kb(),
                )
            return False
        if session.get("generation_id") != generation_id:
            return False
        # Scene and celebrity are immutable for the current job. This prevents a
        # stale callback/result from being published after the user changed them.
        if session.get("generation_scene_snapshot") != scene or session.get("generation_celebrity_snapshot") != celebrity_name:
            session["state"] = "await_scene"
            session.pop("generation_id", None)
            return False
        result_path = engine._store_image(session, "result_refined.png" if refinement else "result.png", output)
        session["result_path"] = result_path
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session.pop("generation_id", None)
        from telegram import InputFile
        bio = BytesIO(output)
        bio.name = "celebrity_selfie.png"
        caption = (
            "📸 Проверенное AI-селфи готово ✅\n"
            f"Персона: {celebrity_name}\n"
            "Контроль: единый кадр, выбранная сцена, обязательный identity-lock.\n"
            "Пометка: изображение создано ИИ; оно не подтверждает реальную встречу, поддержку, рекламу или партнёрство."
        )
        markup = engine._result_kb(bool(engine._selected_entry(session)))
        if engine._flag("CELEBRITY_SELFIE_SEND_AS_DOCUMENT", True):
            await update.effective_message.reply_document(InputFile(bio), caption=caption, reply_markup=markup)
        else:
            await update.effective_message.reply_photo(photo=output, caption=caption, reply_markup=markup)
        return True

    pay = getattr(mod, "_try_pay_then_do", None)
    if not callable(pay):
        await work()
        return
    cost = float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.15) or 0.15)
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind="celebrity_selfie_validated_refine" if refinement else "celebrity_selfie_validated",
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "refs": len(refs),
            "refinement": refinement,
            "generation_id": generation_id,
            "pipeline": VERSION,
        },
    )


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    session = core._session(context, create=False)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if impl.previous._active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        "catalog=30 (ru=20, us=10)\n"
        "selfie_preflight=tolerant\n"
        "scene_input=face_crops_only\n"
        "scene_validation=seam+aspect+face_count\n"
        "piapi_output_parser=explicit_output_only\n"
        "final_validation=local+vision_qc\n"
        "duplicate_jobs=blocked\n"
        "stale_results=blocked\n"
        "raw_draft_delivery=blocked\n"
        f"identity_engine={'ready' if bool(os.environ.get('PIAPI_API_KEY')) else 'missing'}\n"
        f"last_error={(session.get('last_generation_error') or '-')[:700] if session else '-'}"
    )
    raise ApplicationHandlerStop


# Install the v132 primitives before the v130 single-owner handler builder runs.
impl._source_pair = _source_pair
impl._extract_piapi_output = _extract_piapi_output
impl._piapi_task = _piapi_task
impl._identity_lock = _identity_lock
impl._run_quality_generation = _run_validated_generation
impl._diag = _diag
engine._run_multi_reference_generation = _run_validated_generation
engine._generate = _generate

install_builder_hook = impl.install_builder_hook

__all__ = [
    "VERSION",
    "install_builder_hook",
    "_face_crop",
    "_source_pair",
    "_seam_metrics",
    "_visual_similarity",
    "_image_problem",
    "_extract_piapi_output",
    "_scene_draft",
    "_identity_lock",
    "_run_validated_generation",
    "_generate",
]
