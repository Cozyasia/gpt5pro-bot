# -*- coding: utf-8 -*-
"""Celebrity Selfie v130: production identity-lock pipeline.

The v129 wizard is retained, but raw Gemini/Comet drafts are no longer delivered
as finished results.  Every accepted image must pass a mandatory two-face
identity-lock stage through PiAPI multi-face-swap.  The user source portrait is
kept on the left and the selected celebrity source on the right; the rough scene
prompt enforces the same left-to-right layout.  Refinement re-locks the original
identities onto the previous result instead of regenerating the whole scene.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

import httpx
from PIL import Image, ImageFilter, ImageOps, ImageStat

import celebrity_selfie_v129 as previous

core = previous.core
engine = previous.engine

VERSION = "v130-celebrity-selfie-identity-lock-2026-07-19"
_GROUP = -2_000_000_000
_BUILDER_FLAG = "_celebrity_selfie_v130_builder"
_HANDLER_FLAG = "_celebrity_selfie_v130_handlers"
log = logging.getLogger("gpt-bot.celebrity-selfie-v130")

RU_IDS = {
    "ru_roman_abramovich", "ru_marina_aleksandrova", "ru_nikolay_baskov",
    "ru_basta", "ru_sergey_bezrukov", "ru_dima_bilan",
    "ru_elizaveta_boyarskaya", "ru_pavel_durov", "ru_alina_zagitova",
    "ru_filipp_kirkorov", "ru_danila_kozlovskiy", "ru_egor_krid",
    "ru_sergey_lazarev", "ru_dmitriy_nagiev", "ru_habib_nurmagomedov",
    "ru_aleksandr_ovechkin", "ru_kseniya_sobchak", "ru_ivan_urgant",
    "ru_konstantin_habenskiy", "ru_mariya_sharapova",
}
US_IDS = {
    "us_jennifer_aniston", "us_tom_cruise", "us_leonardo_dicaprio",
    "us_robert_downey_jr", "us_dwayne_johnson", "us_angelina_jolie",
    "us_brad_pitt", "us_scarlett_johansson", "us_taylor_swift",
    "us_keanu_reeves",
}
ALLOWED_IDS = RU_IDS | US_IDS

ENTRY_CALLBACKS = set(previous.ENTRY_CALLBACKS) | {
    "cs130:start", "fun:aiselfie", "act:fun:aiselfie", "pedit:aiselfie",
}

# Keep one release identity throughout the reused routing chain.  v126's
# _active() compares the session owner with its module-level VERSION.
previous.VERSION = VERSION
previous.previous.VERSION = VERSION
previous.previous.previous.VERSION = VERSION
previous.previous.previous.previous.VERSION = VERSION
core.VERSION = VERSION
core._GROUP = _GROUP
core.KNOWN_ENTRY_CALLBACKS.update(ENTRY_CALLBACKS)

# Defence in depth: even if stale generated JSON survives a deploy, only the
# curated 20+10 catalog is visible to the wizard/search functions.
if isinstance(getattr(engine, "CATALOG", None), dict):
    engine.CATALOG["celebrities"] = [
        item for item in engine.CATALOG.get("celebrities", [])
        if str(item.get("id") or "") in ALLOWED_IDS
    ]

_ORIGINAL_DRAFT_GENERATOR = engine._run_multi_reference_generation
_ORIGINAL_ACCEPT_USER_PHOTO = core._accept_user_photo
_ORIGINAL_BUILD_PROMPT = engine.build_identity_prompt


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
    return min(maximum, max(minimum, value))


def _jpeg(raw: bytes, max_side: int = 1900, quality: int = 94) -> bytes:
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = BytesIO()
        image.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue()


def _quality_metrics(raw: bytes) -> dict[str, float]:
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


def _quality_problem(metrics: dict[str, float]) -> str:
    min_side = _number("CELEBRITY_SELFIE_MIN_SIDE", 512, 320, 1600)
    min_contrast = _number("CELEBRITY_SELFIE_MIN_CONTRAST", 14, 4, 80)
    min_sharpness = _number("CELEBRITY_SELFIE_MIN_SHARPNESS", 18, 4, 120)
    brightness = metrics.get("brightness", 0)
    if metrics.get("short_side", 0) < min_side:
        return "лицо и фотография слишком маленькие"
    if brightness < 28:
        return "фотография слишком тёмная"
    if brightness > 238:
        return "фотография пересвечена"
    if metrics.get("contrast", 0) < min_contrast:
        return "лицо недостаточно контрастное"
    if metrics.get("sharpness", 0) < min_sharpness:
        return "фотография размыта"
    return ""


def _runtime_detector() -> Any:
    with contextlib.suppress(Exception):
        mod = engine._runtime_module()
        detector = getattr(mod, "_detect_faces_for_choice", None)
        if callable(detector):
            return detector
    return None


async def _face_count(raw: bytes) -> int | None:
    detector = _runtime_detector()
    if not callable(detector):
        return None
    try:
        faces = await asyncio.to_thread(detector, raw)
        return len(faces or [])
    except Exception as exc:
        log.info("Face detector unavailable for quality gate: %s", exc)
        return None


async def _accept_user_photo(update: Any, context: Any, raw: bytes) -> None:
    try:
        normalized = _jpeg(raw, max_side=1900)
        metrics = _quality_metrics(normalized)
        problem = _quality_problem(metrics)
        count = await _face_count(normalized)
        if count == 0:
            problem = "лицо не распознано"
        elif count is not None and count > 1:
            problem = "на фотографии должно быть только одно лицо"
    except Exception as exc:
        log.warning("Selfie preflight failed: %s", exc)
        normalized = b""
        metrics = {}
        problem = "файл изображения повреждён или не поддерживается"

    if problem:
        session = core._session(context)
        session["owner"] = VERSION
        session["state"] = "await_user_photo"
        session["selfie_quality"] = {**metrics, "accepted": False, "reason": problem}
        await update.effective_message.reply_text(
            "❌ Это селфи не подходит для точного переноса лица: " + problem + ".\n\n"
            "Пришлите другое фото: один человек, лицо крупно и полностью видно, анфас или 3/4, "
            "без фильтров, сильной тени, очков и смаза.",
            reply_markup=core._photo_choice_kb(False),
        )
        return

    session = core._session(context)
    session["selfie_quality"] = {**metrics, "accepted": True, "faces": count}
    await _ORIGINAL_ACCEPT_USER_PHOTO(update, context, normalized)


core._accept_user_photo = _accept_user_photo


def _identity_prompt(
    celebrity_name: str,
    scene: str,
    reference_count: int,
    *,
    refinement: bool = False,
) -> str:
    mode = "Refine the supplied draft" if refinement else "Create a new photorealistic smartphone selfie"
    return f"""
{mode} with EXACTLY TWO foreground people and no other detectable foreground faces.
SCENE: {scene}
LAYOUT IS MANDATORY: IMAGE 1 person is on the LEFT; {celebrity_name} is on the RIGHT.
Both faces are at a similar size, upright, on nearly the same horizontal eye line, facing the camera.
Keep background people distant, tiny, out of focus and without recognisable faces.

IDENTITY RULES:
- IMAGE 1 is the user's immutable identity reference. Preserve facial geometry, age, skin tone,
  eye shape, nose, mouth, jaw, hairline and natural asymmetry. Do not beautify, slim, age, feminise,
  masculinise or replace this person.
- The next {reference_count} images all depict the same public figure: {celebrity_name}.
  Preserve that person's recognisable facial geometry and current appearance.
- Do not blend the two identities. Do not swap their positions. Do not invent look-alikes.
- Natural skin texture, realistic lens perspective, plausible hands, coherent lighting.
- The image is a clearly fictional AI-created friendly encounter, not evidence, news, endorsement,
  advertising, political support or a real meeting.
""".strip()


engine.build_identity_prompt = _identity_prompt


def _image_score(raw: bytes) -> float:
    try:
        m = _quality_metrics(raw)
        pixels = m["width"] * m["height"]
        return min(pixels, 5_000_000) / 50_000 + m["sharpness"] * 3 + m["contrast"]
    except Exception:
        return -1


async def _best_reference(refs: Iterable[bytes]) -> bytes:
    ranked: list[tuple[float, bytes]] = []
    detector = _runtime_detector()
    for raw in refs:
        if not raw:
            continue
        score = _image_score(raw)
        if callable(detector):
            try:
                faces = await asyncio.to_thread(detector, raw)
                count = len(faces or [])
                if count == 1:
                    score += 10000
                elif count == 0:
                    score -= 10000
                else:
                    score -= 2000 * (count - 1)
            except Exception:
                pass
        ranked.append((score, raw))
    if not ranked:
        raise RuntimeError("Нет пригодного лицевого референса знаменитости")
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _panel(raw: bytes, size: int = 900) -> Image.Image:
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        return ImageOps.fit(
            image,
            (size, size),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.36),
        )


def _source_pair(user_photo: bytes, celebrity_ref: bytes) -> bytes:
    size = 900
    sheet = Image.new("RGB", (size * 2, size), (32, 32, 32))
    sheet.paste(_panel(user_photo, size), (0, 0))
    sheet.paste(_panel(celebrity_ref, size), (size, 0))
    out = BytesIO()
    sheet.save(out, "JPEG", quality=95, optimize=True)
    return out.getvalue()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _task_id(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and data.get("task_id"):
            return str(data["task_id"])
        if payload.get("task_id"):
            return str(payload["task_id"])
    return ""


def _status(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("status") or "").casefold()
        return str(payload.get("status") or "").casefold()
    return ""


def _error_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:500]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("raw_message") or error.get("detail") or "")[:500]
    return str(data.get("detail") or payload.get("message") or "")[:500]


def _candidate_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        priority = ("image_url", "image_urls", "url", "urls", "result", "output", "image", "images")
        for key in priority:
            if key in value:
                yield from _candidate_strings(value[key])
        for key, child in value.items():
            if key not in priority:
                yield from _candidate_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _candidate_strings(child)


async def _extract_output_image(payload: Any, client: httpx.AsyncClient) -> bytes | None:
    for value in _candidate_strings(payload):
        candidate = value.strip()
        if candidate.startswith("data:image") and "," in candidate:
            with contextlib.suppress(Exception):
                return base64.b64decode(candidate.split(",", 1)[1])
        if candidate.startswith(("https://", "http://")):
            with contextlib.suppress(Exception):
                response = await client.get(candidate)
                if response.status_code < 400 and response.content:
                    return response.content
        if len(candidate) > 1000:
            with contextlib.suppress(Exception):
                decoded = base64.b64decode(candidate, validate=True)
                if decoded:
                    return decoded
    return None


def _piapi_key(mod: Any) -> str:
    return str(getattr(mod, "PIAPI_API_KEY", "") or os.environ.get("PIAPI_API_KEY", "")).strip()


async def _piapi_task(mod: Any, task_type: str, inputs: dict[str, Any]) -> bytes:
    key = _piapi_key(mod)
    if not key:
        raise RuntimeError("Точный модуль фиксации лиц не настроен: отсутствует PIAPI_API_KEY")
    base_url = str(getattr(mod, "PIAPI_BASE_URL", "") or os.environ.get("PIAPI_BASE_URL") or "https://api.piapi.ai").rstrip("/")
    create_path = str(getattr(mod, "PIAPI_FACE_CREATE_PATH", "") or os.environ.get("PIAPI_FACE_CREATE_PATH") or "/api/v1/task")
    status_path = str(getattr(mod, "PIAPI_FACE_STATUS_PATH", "") or os.environ.get("PIAPI_FACE_STATUS_PATH") or "/api/v1/task/{task_id}")
    model = str(getattr(mod, "PIAPI_FACE_MODEL", "") or os.environ.get("PIAPI_FACE_MODEL") or "Qubico/image-toolkit")
    timeout_s = _number("CELEBRITY_IDENTITY_TIMEOUT_S", 300, 60, 900)
    poll_s = _number("CELEBRITY_IDENTITY_POLL_S", 2.5, 1, 15)
    deadline = time.monotonic() + timeout_s
    headers = {"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    body = {"model": model, "task_type": task_type, "input": inputs}

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=30), follow_redirects=True) as client:
        response = await client.post(base_url + create_path, headers=headers, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"Identity-lock provider HTTP {response.status_code}: {response.text[:400]}")
        payload = response.json()
        task_id = _task_id(payload)
        if not task_id:
            raise RuntimeError("Identity-lock provider не вернул task_id")
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_s)
            status_response = await client.get(
                base_url + status_path.replace("{task_id}", task_id),
                headers={"x-api-key": key, "Accept": "application/json"},
            )
            if status_response.status_code >= 400:
                continue
            payload = status_response.json()
            state = _status(payload)
            if state in {"completed", "success", "succeeded", "finished"}:
                raw = await _extract_output_image(payload, client)
                if raw:
                    return _jpeg(raw, max_side=1900, quality=96)
                raise RuntimeError("Identity-lock provider завершил задачу без изображения")
            if state in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError("Identity-lock provider: " + (_error_text(payload) or state))
        raise RuntimeError("Identity-lock provider превысил время ожидания")


async def _identity_lock(mod: Any, user_photo: bytes, celebrity_ref: bytes, target: bytes) -> bytes:
    source = _source_pair(user_photo, celebrity_ref)
    target = _jpeg(target, max_side=1900, quality=95)
    locked = await _piapi_task(
        mod,
        "multi-face-swap",
        {
            "swap_image": _b64(source),
            "target_image": _b64(target),
            "swap_faces_index": "0,1",
            "target_faces_index": "0,1",
        },
    )
    count = await _face_count(locked)
    if count is not None and count < 2:
        raise RuntimeError("Проверка результата не нашла два уверенных лица")
    return locked


async def _run_quality_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
) -> bytes | None:
    if not user_photo:
        raise RuntimeError("Исходное селфи пользователя отсутствует")
    best_ref = await _best_reference(celebrity_refs)

    # Refinement is deliberately face-only: preserve the accepted scene and
    # reapply both original identities. Initial generation creates a draft first.
    if previous_result:
        draft = previous_result
    else:
        draft = await _ORIGINAL_DRAFT_GENERATOR(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            previous_result=None,
        )
    if not draft:
        raise RuntimeError("Не удалось создать базовую сцену")

    if not _flag("CELEBRITY_IDENTITY_LOCK_REQUIRED", True):
        return await _identity_lock(mod, user_photo, best_ref, draft)

    attempts = int(_number("CELEBRITY_IDENTITY_ATTEMPTS", 2, 1, 4))
    last_error = ""
    for _ in range(attempts):
        try:
            return await _identity_lock(mod, user_photo, best_ref, draft)
        except Exception as exc:
            last_error = str(exc)
            log.warning("Celebrity identity-lock attempt failed: %s", exc)
    # Never leak the weak raw draft as a supposedly exact result.
    raise RuntimeError(
        "Не удалось надёжно закрепить оба лица. Плохой черновик не отправлен. "
        + (last_error[:500] if last_error else "Повторите позже или загрузите другие референсы.")
    )


engine._run_multi_reference_generation = _run_quality_generation


def _owned_callback(data: str) -> bool:
    value = str(data or "").casefold()
    return (
        data in ENTRY_CALLBACKS
        or "aiselfie" in value or "ai_selfie" in value or "ai-selfie" in value
        or str(data or "").startswith(("cs126:", "cs127:", "cs128:", "cs129:", "cs130:", "celeb:"))
    )


async def _callback(update: Any, context: Any) -> None:
    query = getattr(update, "callback_query", None)
    data = str(getattr(query, "data", "") or "") if query is not None else ""
    if not _owned_callback(data):
        return
    await previous._callback(update, context)


async def _image(update: Any, context: Any) -> None:
    if not previous._active(context):
        return
    await previous._image(update, context)


async def _text(update: Any, context: Any) -> None:
    if not previous._active(context):
        return
    await previous._text(update, context)


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    session = core._session(context, create=False)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if previous._active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        f"handler_group={_GROUP}\n"
        "catalog=30 (ru=20, us=10)\n"
        "selfie_preflight=enabled\n"
        "quality_pipeline=gemini_scene+piapi_multi_face_identity_lock\n"
        "refinement=face_only\n"
        "raw_draft_delivery=blocked\n"
        f"identity_engine={'ready' if bool(os.environ.get('PIAPI_API_KEY')) else 'key-from-runtime-or-missing'}"
    )
    raise ApplicationHandlerStop


def _install_handlers(app: Any) -> None:
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    if getattr(app, _HANDLER_FLAG, False):
        return
    pattern = r"^(?:.*(?:aiselfie|ai_selfie|ai-selfie).*|cs126:.*|cs127:.*|cs128:.*|cs129:.*|cs130:.*|celeb:.*)$"
    app.add_handler(CallbackQueryHandler(_callback, pattern=pattern), group=_GROUP)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, _image), group=_GROUP)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=_GROUP)
    app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_GROUP)
    app.add_error_handler(previous.previous.previous._error_handler)
    setattr(app, _HANDLER_FLAG, True)


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        _install_handlers(app)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = [
    "VERSION", "RU_IDS", "US_IDS", "_quality_metrics", "_quality_problem",
    "_source_pair", "_extract_output_image", "_run_quality_generation",
    "install_builder_hook",
]
