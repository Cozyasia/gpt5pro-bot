# -*- coding: utf-8 -*-
"""Celebrity Selfie v133: best-of-N generation with provider fallback and retry UX.

v132 correctly stopped technical composites from reaching users, but a single
candidate could still fail quality control and leave the user without a result.
v133 creates several independent scene candidates, ranks them, applies identity
locking to the strongest candidates, optionally falls back to OpenAI Images, and
shows one actionable failure card instead of duplicate generic errors.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import time
import uuid
from io import BytesIO
from typing import Any

import httpx
from PIL import Image, ImageOps

import celebrity_selfie_v132 as base
import celebrity_selfie_v132_guard as base_guard

VERSION = "v133-celebrity-selfie-best-of-n-fallback-2026-07-19"
engine = base.engine
impl = base.impl
log = logging.getLogger("gpt-bot.celebrity-selfie-v133")

for _module in (base, base.previous, impl, engine, base_guard):
    with contextlib.suppress(Exception):
        _module.VERSION = VERSION


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(float(os.environ.get(name, str(default)) or default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _scene_profile(scene: str) -> str:
    low = str(scene or "").casefold().replace("ё", "е")
    if "красн" in low and "площад" in low:
        return (
            "Recognisable Red Square in Moscow behind the pair: Saint Basil's Cathedral and Kremlin architecture "
            "visible in one coherent perspective, open public square, natural daylight, tourist smartphone selfie."
        )
    if "яхт" in low or "море" in low:
        return (
            "On the open deck of one modern yacht at sea, coherent railings and horizon, daylight, casual luxury, "
            "both people physically together in the same smartphone frame."
        )
    if "ресторан" in low:
        return (
            "Inside one modern restaurant at a shared table, warm practical lighting, both people at the same depth, "
            "clear faces, realistic hands, no unrelated diners dominating the foreground."
        )
    if "премьер" in low or "дорожк" in low:
        return (
            "At one film-premiere red carpet, evening flash photography and event backdrop, elegant clothing, "
            "natural fan selfie, no logos or readable sponsor text."
        )
    if "выстав" in low or "антик" in low:
        return (
            "Inside one public art or antiques exhibition, coherent display cases and exhibits in the background, "
            "neutral friendly meeting without advertising or endorsement cues."
        )
    return str(scene or "natural public location")


def _scene_prompt(celebrity_name: str, scene: str, variant: int) -> str:
    framings = (
        "arm-length smartphone selfie, heads and upper torsos visible",
        "friendly shoulder-to-shoulder medium selfie, equal eye line",
        "slightly wider vertical smartphone selfie, both faces large and unobstructed",
    )
    framing = framings[variant % len(framings)]
    return (
        "Create exactly ONE seamless photorealistic vertical smartphone photograph in ONE continuous camera frame. "
        "Never create a collage, diptych, split screen, before/after, contact sheet, reference board, border or divider. "
        "Exactly TWO main adults are physically together: placeholder A on the LEFT and placeholder B on the RIGHT. "
        f"Placeholder B should only have the broad age/build of {celebrity_name}; precise identity is added later. "
        "Both faces must be frontal or gentle 3/4, upright, unobstructed, similarly sized, well lit and separated enough "
        "for a later two-face swap. Do not copy the supplied reference backgrounds, clothes, table, walls or objects. "
        "No third foreground person, duplicate body, extra face, poster portrait, phone screen portrait, text or watermark. "
        f"Composition: {framing}. Location contract: {_scene_profile(scene)} "
        "Natural skin texture, coherent lighting and perspective, realistic anatomy, portrait 4:5. Return only the image."
    )


def _candidate_local_score(raw: bytes) -> float:
    """Cheap 0..100 composition score used before provider-intensive identity lock."""
    problem = base._image_problem(raw, stage="кандидате сцены", require_two_faces=True)
    if problem:
        return 0.0
    image = base._open_rgb(raw)
    seam = base._seam_metrics(raw)
    ratio = image.width / float(max(1, image.height))
    score = 72.0
    if 0.68 <= ratio <= 0.95:
        score += 12.0
    elif 0.55 <= ratio <= 1.25:
        score += 6.0
    score += max(0.0, 8.0 - min(8.0, seam.get("seam_ratio", 0.0)))
    boxes = base._face_boxes(raw)
    if len(boxes) == 2:
        score += 8.0
    elif boxes:
        score -= abs(len(boxes) - 2) * 8.0
    return max(0.0, min(100.0, score))


def _json_object(text: str) -> dict[str, Any] | None:
    return base._extract_json(text)


async def _vision_candidate_score(mod: Any, raw: bytes, scene: str) -> tuple[float, str]:
    vision = getattr(mod, "ask_openai_vision", None)
    if not _flag("CELEBRITY_VISION_RANKING", True) or not callable(vision):
        return _candidate_local_score(raw), "local"
    prompt = (
        "Evaluate this candidate for a two-person celebrity selfie. Do not identify anyone. Return strict JSON: "
        "single_scene boolean, split_screen boolean, foreground_people integer, scene_match boolean, "
        "composition_score integer 0-100, face_swap_readiness integer 0-100, reason short string. "
        f"Requested scene: {scene[:700]}"
    )
    try:
        answer = await vision(prompt, base64.b64encode(raw).decode("ascii"), "image/jpeg")
        data = _json_object(answer)
        if not data:
            return _candidate_local_score(raw), "vision-unparsed"
        if data.get("single_scene") is False or data.get("split_screen") is True:
            return 0.0, str(data.get("reason") or "split-screen")
        people = data.get("foreground_people")
        if isinstance(people, (int, float)) and int(people) != 2:
            return 0.0, f"foreground_people={int(people)}"
        if data.get("scene_match") is False:
            return 0.0, str(data.get("reason") or "scene mismatch")
        composition = float(data.get("composition_score") or 0)
        readiness = float(data.get("face_swap_readiness") or 0)
        local = _candidate_local_score(raw)
        return max(0.0, min(100.0, local * 0.25 + composition * 0.35 + readiness * 0.40)), str(data.get("reason") or "vision")
    except Exception as exc:
        log.info("Candidate ranking vision unavailable: %s", exc)
        return _candidate_local_score(raw), "vision-error"


def _comet_models(mod: Any) -> list[str]:
    values: list[str] = []
    primary = str(getattr(mod, "COMET_IMAGE_EDIT_MODEL", "") or "").strip()
    if primary:
        values.append(primary)
    for value in list(getattr(mod, "COMET_IMAGE_EDIT_FALLBACK_MODELS", []) or []):
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)
    if not values:
        values = ["gemini-2.5-flash-image"]
    return values


async def _comet_scene_candidate(
    mod: Any,
    user_crop: bytes,
    celebrity_crop: bytes,
    celebrity_name: str,
    scene: str,
    candidate_index: int,
) -> bytes:
    api_key = str(getattr(mod, "COMET_API_KEY", "") or os.environ.get("COMET_API_KEY") or "")
    if not api_key:
        raise RuntimeError("COMET_API_KEY не задан")
    models = _comet_models(mod)
    model = models[candidate_index % len(models)]
    base_url = str(getattr(mod, "COMET_BASE_URL", "https://api.cometapi.com") or "").rstrip("/")
    path_template = str(getattr(mod, "COMET_IMAGE_EDIT_PATH", "/v1beta/models/{model}:generateContent") or "")
    url = base_url + path_template.replace("{model}", model)
    timeout_s = _integer("CELEBRITY_SCENE_TIMEOUT_S", 420, 90, 900)
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"}
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180), follow_redirects=True) as client:
        for camel in (True, False):
            prompt = _scene_prompt(celebrity_name, scene, candidate_index)
            parts: list[dict[str, Any]] = [
                {"text": prompt},
                {"text": "REFERENCE A: face-only cue for LEFT placeholder; never copy its original environment."},
                engine._image_part(mod, user_crop, 768, camel),
                {"text": "REFERENCE B: face-only cue for RIGHT placeholder; never copy its original environment."},
                engine._image_part(mod, celebrity_crop, 768, camel),
            ]
            config = {"responseModalities": ["TEXT", "IMAGE"]} if camel else {"response_modalities": ["TEXT", "IMAGE"]}
            payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code >= 400:
                    errors.append(f"{model} HTTP {response.status_code}: {response.text[:180]}")
                    continue
                output = None
                extractor = getattr(mod, "_image_bytes_from_response", None)
                if callable(extractor):
                    output = await extractor(response, client)
                if not output:
                    with contextlib.suppress(Exception):
                        output = base._gemini_image_from_json(response.json())
                if not output:
                    errors.append(f"{model}: empty image")
                    continue
                output = impl._jpeg(output, max_side=1900, quality=95)
                problem = base._image_problem(output, stage="кандидате сцены", require_two_faces=True)
                if problem:
                    errors.append(f"{model}: {problem}")
                    continue
                return output
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Comet scene candidate failed: " + " | ".join(errors[-4:])[:700])


async def _openai_scene_candidate(
    mod: Any,
    user_crop: bytes,
    celebrity_crop: bytes,
    celebrity_name: str,
    scene: str,
) -> bytes:
    """Optional second-provider fallback using the official Images edit endpoint."""
    key = str(getattr(mod, "OPENAI_IMAGE_KEY", "") or getattr(mod, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_IMAGE_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OpenAI Images key отсутствует")
    base_url = str(getattr(mod, "IMAGES_BASE_URL", "") or os.environ.get("OPENAI_IMAGE_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = str(getattr(mod, "IMAGES_MODEL", "") or os.environ.get("OPENAI_IMAGE_MODEL") or "gpt-image-1")
    prompt = _scene_prompt(celebrity_name, scene, 2)
    data = {
        "model": model,
        "prompt": prompt,
        "size": "1024x1536",
        "quality": "high",
        "input_fidelity": "low",
        "output_format": "jpeg",
    }
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    timeout_s = _integer("CELEBRITY_OPENAI_SCENE_TIMEOUT_S", 420, 90, 900)
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180), follow_redirects=True) as client:
        for field in ("image[]", "image"):
            files = [
                (field, ("left-user-face.jpg", user_crop, "image/jpeg")),
                (field, ("right-celebrity-face.jpg", celebrity_crop, "image/jpeg")),
            ]
            try:
                response = await client.post(base_url + "/images/edits", headers=headers, data=data, files=files)
                if response.status_code >= 400:
                    errors.append(f"OpenAI HTTP {response.status_code}: {response.text[:220]}")
                    continue
                payload = response.json()
                rows = payload.get("data") if isinstance(payload, dict) else None
                row = rows[0] if isinstance(rows, list) and rows else {}
                raw = None
                if isinstance(row, dict) and isinstance(row.get("b64_json"), str):
                    raw = base64.b64decode(row["b64_json"])
                elif isinstance(row, dict) and isinstance(row.get("url"), str):
                    image_response = await client.get(row["url"])
                    if image_response.status_code < 400:
                        raw = image_response.content
                if not raw:
                    errors.append("OpenAI Images returned no image")
                    continue
                output = impl._jpeg(raw, max_side=1900, quality=95)
                problem = base._image_problem(output, stage="резервном кандидате сцены", require_two_faces=True)
                if problem:
                    errors.append(problem)
                    continue
                return output
            except Exception as exc:
                errors.append(f"OpenAI Images: {type(exc).__name__}: {exc}")
    raise RuntimeError("OpenAI scene fallback failed: " + " | ".join(errors[-4:])[:700])


async def _identity_similarity_qc(
    mod: Any,
    output: bytes,
    user_photo: bytes,
    celebrity_ref: bytes,
    scene: str,
) -> tuple[float, str]:
    """Compare both identities using a compact labelled board; fail open if Vision is unavailable."""
    vision = getattr(mod, "ask_openai_vision", None)
    if not _flag("CELEBRITY_IDENTITY_VISION_QC", True) or not callable(vision):
        return 70.0, "identity-vision-unavailable"
    user = ImageOps.fit(base._open_rgb(base._face_crop(user_photo, 512)), (512, 512), method=Image.Resampling.LANCZOS)
    celeb = ImageOps.fit(base._open_rgb(base._face_crop(celebrity_ref, 512)), (512, 512), method=Image.Resampling.LANCZOS)
    final = ImageOps.fit(base._open_rgb(output), (768, 512), method=Image.Resampling.LANCZOS)
    board = Image.new("RGB", (1792, 512), (24, 24, 24))
    board.paste(user, (0, 0))
    board.paste(celeb, (512, 0))
    board.paste(final, (1024, 0))
    board_raw = base._encode_jpeg(board, 92)
    prompt = (
        "The image is a three-panel QA board: LEFT=user reference, MIDDLE=public-person reference, RIGHT=final scene. "
        "Do not identify or name anyone. Compare facial appearance only. Return strict JSON: "
        "user_similarity integer 0-100, celebrity_similarity integer 0-100, two_distinct_people boolean, "
        "scene_match boolean, reason short string. The final scene must contain both distinct referenced faces. "
        f"Requested scene: {scene[:500]}"
    )
    try:
        answer = await vision(prompt, base64.b64encode(board_raw).decode("ascii"), "image/jpeg")
        data = _json_object(answer)
        if not data:
            return 70.0, "identity-vision-unparsed"
        if data.get("two_distinct_people") is False:
            return 0.0, str(data.get("reason") or "identities blended")
        if data.get("scene_match") is False:
            return 0.0, str(data.get("reason") or "scene mismatch")
        user_score = float(data.get("user_similarity") or 0)
        celeb_score = float(data.get("celebrity_similarity") or 0)
        minimum = min(user_score, celeb_score)
        threshold = float(_integer("CELEBRITY_MIN_IDENTITY_SCORE", 58, 35, 90))
        if minimum < threshold:
            return 0.0, f"identity scores user={user_score:.0f}, celebrity={celeb_score:.0f}"
        return min(100.0, user_score * 0.52 + celeb_score * 0.48), str(data.get("reason") or "identity-ok")
    except Exception as exc:
        log.info("Identity Vision QC unavailable: %s", exc)
        return 70.0, "identity-vision-error"


async def _run_best_of_n_generation(
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

    if previous_result:
        output = await base._identity_lock(mod, user_photo, best_ref, previous_result)
        scene_problem = await base._vision_qc(mod, output, scene)
        if scene_problem:
            raise RuntimeError(scene_problem)
        identity_score, reason = await _identity_similarity_qc(mod, output, user_photo, best_ref, scene)
        if identity_score <= 0:
            raise RuntimeError("Улучшение сходства отклонено: " + reason)
        return output

    candidate_count = _integer("CELEBRITY_SCENE_CANDIDATES", 3, 2, 4)
    identity_count = _integer("CELEBRITY_IDENTITY_CANDIDATES", 2, 1, candidate_count)
    user_crop = base._face_crop(user_photo, 768)
    celebrity_crop = base._face_crop(best_ref, 768)
    drafts: list[tuple[float, bytes, str]] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(_integer("CELEBRITY_SCENE_PARALLEL", 2, 1, 3))

    async def make(index: int) -> None:
        async with semaphore:
            try:
                raw = await _comet_scene_candidate(mod, user_crop, celebrity_crop, celebrity_name, scene, index)
                score, reason = await _vision_candidate_score(mod, raw, scene)
                if score > 0:
                    drafts.append((score, raw, f"comet-{index + 1}:{reason}"))
                else:
                    errors.append(f"candidate {index + 1} rejected: {reason}")
            except Exception as exc:
                errors.append(f"candidate {index + 1}: {type(exc).__name__}: {exc}")

    await asyncio.gather(*(make(index) for index in range(candidate_count)))

    if len(drafts) < identity_count and _flag("CELEBRITY_OPENAI_SCENE_FALLBACK", True):
        try:
            raw = await _openai_scene_candidate(mod, user_crop, celebrity_crop, celebrity_name, scene)
            score, reason = await _vision_candidate_score(mod, raw, scene)
            if score > 0:
                drafts.append((score, raw, f"openai:{reason}"))
            else:
                errors.append("OpenAI candidate rejected: " + reason)
        except Exception as exc:
            errors.append(f"OpenAI fallback: {type(exc).__name__}: {exc}")

    if not drafts:
        raise RuntimeError("Не получено ни одной цельной сцены. " + " | ".join(errors[-6:])[:1100])

    drafts.sort(key=lambda item: item[0], reverse=True)
    finals: list[tuple[float, bytes, str]] = []
    for draft_score, draft, label in drafts[:identity_count]:
        try:
            output = await base._identity_lock(mod, user_photo, best_ref, draft)
            scene_problem = await base._vision_qc(mod, output, scene)
            if scene_problem:
                raise RuntimeError(scene_problem)
            identity_score, identity_reason = await _identity_similarity_qc(mod, output, user_photo, best_ref, scene)
            if identity_score <= 0:
                raise RuntimeError(identity_reason)
            total = draft_score * 0.35 + identity_score * 0.65
            finals.append((total, output, f"{label}; {identity_reason}"))
            if total >= float(_integer("CELEBRITY_EARLY_ACCEPT_SCORE", 84, 65, 98)):
                break
        except Exception as exc:
            errors.append(f"identity {label}: {type(exc).__name__}: {exc}")

    if not finals:
        raise RuntimeError(
            "Ни один из лучших кандидатов не прошёл закрепление и проверку двух лиц. "
            + " | ".join(errors[-8:])[:1300]
        )
    finals.sort(key=lambda item: item[0], reverse=True)
    return finals[0][1]


def _failure_kb():
    return engine._kb([
        [("🔁 Повторить эту же сцену", "celeb:retry_scene")],
        [("🎬 Премьера", "celeb:preset:redcarpet"), ("🍽 Ресторан", "celeb:preset:restaurant")],
        [("⛵ Яхта", "celeb:preset:yacht"), ("🏛 Выставка", "celeb:preset:exhibition")],
        [("🏙 Красная площадь", "celeb:preset:red_square")],
        [("⭐ Сменить знаменитость", "celeb:menu"), ("❌ Отмена", "celeb:cancel")],
    ])


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Откройте режим заново.")
        return
    now = time.monotonic()
    state = str(session.get("state") or "")
    started = float(session.get("generation_started_monotonic") or 0)
    if state in {"queued", "generating"} and now - started < 1200:
        await update.effective_message.reply_text("⏳ Эта генерация уже выполняется. Дождитесь результата.")
        return

    user_photo = engine._read_path(session.get("user_photo_path"))
    refs = [raw for raw in (engine._read_path(path) for path in engine._reference_paths(session)) if raw]
    scene = str(session.get("scene") or "").strip()
    celebrity_name = str(session.get("celebrity_name") or "выбранный человек").strip()
    if not user_photo:
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text("Пришлите своё селфи ещё раз.")
        return
    if not refs:
        session["state"] = "await_custom_refs"
        await update.effective_message.reply_text("Загрузите 1–4 фото знаменитости.")
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
        if not base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            return True
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Повторно закрепляю исходные лица без изменения сцены…" if refinement else
            f"⏳ Создаю до {_integer('CELEBRITY_SCENE_CANDIDATES', 3, 2, 4)} вариантов сцены с {celebrity_name}, "
            "выбираю лучший и закрепляю оба лица. Ожидание обычно 3–8 минут."
        )
        try:
            output = await _run_best_of_n_generation(
                mod, user_photo, refs, celebrity_name, scene, previous_result=previous_result
            )
        except Exception as exc:
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "result" if previous_result else "await_scene"
                session["last_generation_error"] = str(exc)[:1800]
                session["last_generation_failed_at"] = time.time()
                session["generation_failures"] = int(session.get("generation_failures") or 0) + 1
                session.pop("generation_id", None)
                failures = int(session.get("generation_failures") or 0)
                hint = (
                    " После двух неудачных попыток обычно лучше выбрать «Премьера» или «Ресторан»: "
                    "там лица занимают больше кадра."
                    if failures >= 2 else ""
                )
                await update.effective_message.reply_text(
                    "❌ Качественный результат не получен, поэтому изображение не отправлено. "
                    + base_guard._public_failure(exc)
                    + ". Можно повторить тот же сюжет одним нажатием или выбрать другую сцену."
                    + hint,
                    reply_markup=_failure_kb(),
                )
            return True

        if not base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            if str(session.get("generation_id") or "") == generation_id:
                session.pop("generation_id", None)
            return True

        result_path = engine._store_image(session, "result_refined.png" if refinement else "result.png", output)
        session["result_path"] = result_path
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session["generation_failures"] = 0
        session.pop("generation_id", None)

        from telegram import InputFile
        bio = BytesIO(output)
        bio.name = "celebrity_selfie.png"
        caption = (
            "📸 Проверенное AI-селфи готово ✅\n"
            f"Персона: {celebrity_name}\n"
            "Контроль: best-of-N, единый кадр, соответствие сцене и закрепление двух лиц.\n"
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
        remember_kind="celebrity_selfie_best_of_n_refine" if refinement else "celebrity_selfie_best_of_n",
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "refinement": refinement,
            "generation_id": generation_id,
            "pipeline": VERSION,
            "scene_candidates": _integer("CELEBRITY_SCENE_CANDIDATES", 3, 2, 4),
        },
    )


_ORIGINAL_CALLBACK = engine._on_callback


async def _on_callback(update: Any, context: Any) -> None:
    data = str(getattr(getattr(update, "callback_query", None), "data", "") or "")
    if data == "celeb:retry_scene":
        with contextlib.suppress(Exception):
            await update.callback_query.answer()
        await _generate(update, context, refinement=False)
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop
    await _ORIGINAL_CALLBACK(update, context)


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    session = engine._session(context, create=False)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if base.impl.previous._active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        "catalog=30 (ru=20, us=10)\n"
        "selfie_preflight=tolerant\n"
        f"scene_candidates={_integer('CELEBRITY_SCENE_CANDIDATES', 3, 2, 4)}\n"
        f"identity_candidates={_integer('CELEBRITY_IDENTITY_CANDIDATES', 2, 1, 4)}\n"
        "provider_chain=comet_best_of_n+openai_images_fallback+piapi_identity_lock\n"
        "scene_templates=profile_specific\n"
        "candidate_ranking=local+vision\n"
        "identity_validation=vision_compare+local_qc\n"
        "failure_ux=single_actionable_card\n"
        "same_scene_retry=enabled\n"
        "duplicate_jobs=blocked\n"
        "stale_results=blocked\n"
        "raw_draft_delivery=blocked\n"
        f"identity_engine={'ready' if bool(os.environ.get('PIAPI_API_KEY')) else 'missing'}\n"
        f"last_error={(session.get('last_generation_error') or '-')[:700] if session else '-'}"
    )
    raise ApplicationHandlerStop


base._scene_prompt = _scene_prompt
base._run_validated_generation = _run_best_of_n_generation
base.impl._run_quality_generation = _run_best_of_n_generation
engine._run_multi_reference_generation = _run_best_of_n_generation
engine._generate = _generate
engine._on_callback = _on_callback
base.impl._diag = _diag

install_builder_hook = base.install_builder_hook

__all__ = [
    "VERSION",
    "install_builder_hook",
    "_scene_profile",
    "_scene_prompt",
    "_candidate_local_score",
    "_comet_scene_candidate",
    "_openai_scene_candidate",
    "_identity_similarity_qc",
    "_run_best_of_n_generation",
    "_failure_kb",
    "_generate",
    "_on_callback",
]
