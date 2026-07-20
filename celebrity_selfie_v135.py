# -*- coding: utf-8 -*-
"""Celebrity Selfie v135: native Gemini 3 multi-reference identity generation."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import os
import time
import uuid
from io import BytesIO
from typing import Any

import httpx

import celebrity_selfie_v134 as previous

VERSION = "v135-celebrity-selfie-gemini3-native-identity-2026-07-20"
v133 = previous.previous
base = previous.base
engine = previous.engine
impl = previous.impl
base_guard = v133.base_guard
log = logging.getLogger("gpt-bot.celebrity-selfie-v135")
_LEGACY_RUN = previous._run_face_first_generation
_LAST_RUN_DEBUG: dict[str, Any] = {}

for _module in (previous, v133, base, base.previous, impl, engine, base_guard):
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


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return int(round(_number(name, float(default), float(minimum), float(maximum))))


def _runtime_value(mod: Any, name: str, default: str = "") -> str:
    return str(getattr(mod, name, "") or os.environ.get(name) or default).strip()


def _gemini_key(mod: Any) -> str:
    for name in ("GEMINI_IMAGE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = _runtime_value(mod, name)
        if value:
            return value
    return ""


def _normalise_model(value: Any) -> str:
    model = str(value or "").strip()
    return (
        model.replace("gemini-3-pro-image-preview", "gemini-3-pro-image")
        .replace("gemini-3.1-flash-image-preview", "gemini-3.1-flash-image")
        .replace("gemini-2-5-", "gemini-2.5-")
    )


def _gemini_models(mod: Any) -> list[str]:
    values: list[str] = []
    configured = str(os.environ.get("CELEBRITY_GEMINI_MODELS") or "").strip()
    if configured:
        values.extend(part.strip() for part in configured.split(",") if part.strip())
    values.extend([
        _runtime_value(mod, "GEMINI_IMAGE_MODEL", "gemini-3-pro-image"),
        _runtime_value(mod, "GEMINI_IMAGE_FALLBACK_MODEL", "gemini-3.1-flash-image"),
    ])
    result: list[str] = []
    allow_preview = _flag("CELEBRITY_ALLOW_PREVIEW_IMAGE_MODELS", False)
    for raw in values:
        model = _normalise_model(raw)
        if not model or ("preview" in model.casefold() and not allow_preview):
            continue
        if model not in result:
            result.append(model)
    return result or ["gemini-3-pro-image", "gemini-3.1-flash-image"]


def _native_prompt(celebrity_name: str, scene: str, variant: int, *, refinement: bool = False) -> str:
    if refinement:
        return (
            "Edit the FIRST supplied image only. Preserve its exact scene, camera, bodies, pose, clothing, lighting and "
            "background. Replace/refine only the two facial identities from the labelled references. LEFT must match USER "
            f"REFERENCE exactly; RIGHT must match PUBLIC FIGURE REFERENCE ({celebrity_name}) exactly. Preserve hairline, "
            "head shape, age, pores, eye spacing, nose, mouth and jaw. Do not beautify, average, merge or clone faces. Keep "
            "exactly two adults in one seamless photograph. No collage, inset, split screen, border, text or watermark."
        )
    framing = (
        "close arm-length phone selfie, both heads and upper torsos large",
        "natural shoulder-to-shoulder smartphone selfie, equal eye line",
        "slightly wider candid phone selfie with one clear environmental cue",
    )[int(variant) % 3]
    return (
        "Generate ONE seamless highly photorealistic smartphone selfie in one continuous frame. Exactly TWO adults are "
        "physically together. LEFT must preserve the exact USER REFERENCE identity: facial proportions, eyes, nose, lips, "
        "jaw, hairline, age and natural skin. RIGHT must preserve the exact PUBLIC FIGURE REFERENCE identity "
        f"({celebrity_name}) with the same fidelity. References are identity-only; never copy their rooms, clothes, borders "
        "or layouts. Do not blend identities, create look-alikes, beautify faces, alter age or distinctive features. Both "
        f"faces are upright, unobstructed, similarly sharp and lit by the same real light. Composition: {framing}. "
        f"{previous._scene_profile(scene)} Natural phone lens perspective, pores, hair, hands and shadows; mild depth of "
        "field, no glamour retouch. No third foreground person, duplicate body, extra face, poster or phone-screen portrait, "
        "collage, split screen, inset, divider, text, logo or watermark. Portrait 4:5. Return only the final image."
    )


def _image_part(raw: bytes) -> dict[str, Any]:
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(raw).decode("ascii")}}


def _reference_parts(
    user_photo: bytes,
    celebrity_refs: list[bytes],
    best_ref: bytes,
    *,
    previous_result: bytes | None = None,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if previous_result:
        parts += [
            {"text": "FIRST IMAGE — accepted scene; preserve everything except the two identities."},
            _image_part(impl._jpeg(previous_result, max_side=1800, quality=95)),
        ]
    parts += [
        {"text": "USER REFERENCE — identity for LEFT only."},
        _image_part(base._face_crop(user_photo, 1024)),
        {"text": "PUBLIC FIGURE REFERENCE — identity for RIGHT only."},
        _image_part(base._face_crop(best_ref, 1024)),
    ]
    max_refs = _integer("CELEBRITY_GEMINI_MAX_REFERENCES", 4, 2, 6)
    seen = {hashlib.sha256(best_ref).digest()}
    for raw in celebrity_refs:
        digest = hashlib.sha256(raw).digest()
        if digest in seen:
            continue
        seen.add(digest)
        if sum("inline_data" in item for item in parts) >= max_refs:
            break
        parts += [
            {"text": "ADDITIONAL VIEW OF THE SAME PUBLIC FIGURE — not another person."},
            _image_part(base._face_crop(raw, 1024)),
        ]
    return parts


def _gemini_payload(prompt: str, refs: list[dict[str, Any]], *, aspect: str, image_size: str) -> dict[str, Any]:
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}, *refs]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "responseFormat": {"image": {"aspectRatio": aspect, "imageSize": image_size}},
        },
    }


def _gemini_images(payload: Any) -> list[bytes]:
    result: list[bytes] = []
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    for candidate in candidates if isinstance(candidates, list) else []:
        content = candidate.get("content") if isinstance(candidate, dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        for part in parts if isinstance(parts, list) else []:
            inline = (part.get("inlineData") or part.get("inline_data")) if isinstance(part, dict) else None
            data = inline.get("data") if isinstance(inline, dict) else None
            if not isinstance(data, str) or len(data) < 200:
                continue
            with contextlib.suppress(Exception):
                raw = base64.b64decode(data, validate=False)
                if raw:
                    result.append(raw)
    return result


def _gemini_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:500]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or error)[:500]
    feedback = payload.get("promptFeedback")
    return str(feedback.get("blockReason") or feedback)[:500] if isinstance(feedback, dict) else ""


async def _gemini_generate(mod: Any, model: str, prompt: str, refs: list[dict[str, Any]]) -> bytes:
    key = _gemini_key(mod)
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY отсутствует")
    base_url = _runtime_value(mod, "GEMINI_IMAGE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    aspect = os.environ.get("CELEBRITY_GEMINI_ASPECT") or _runtime_value(mod, "AI_SELFIE_DEFAULT_ASPECT", "4:5")
    image_size = (os.environ.get("CELEBRITY_GEMINI_IMAGE_SIZE") or _runtime_value(mod, "AI_SELFIE_IMAGE_SIZE", "2K")).upper()
    if image_size not in {"512", "1K", "2K", "4K"}:
        image_size = "2K"
    timeout_s = _integer("CELEBRITY_GEMINI_TIMEOUT_S", int(float(_runtime_value(mod, "GEMINI_IMAGE_TIMEOUT_S", "300"))), 90, 900)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180), follow_redirects=True) as client:
        response = await client.post(
            f"{base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
            json=_gemini_payload(prompt, refs, aspect=aspect, image_size=image_size),
        )
    try:
        data: Any = response.json()
    except Exception as exc:
        raise RuntimeError(f"Gemini {model} returned invalid JSON: {response.text[:400]}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini {model} HTTP {response.status_code}: {_gemini_error(data) or response.text[:400]}")
    errors: list[str] = []
    for raw in reversed(_gemini_images(data)):
        try:
            output = impl._jpeg(raw, max_side=_integer("AI_SELFIE_MAX_SIDE", 1800, 1024, 3072), quality=96)
            problem = base._image_problem(output, stage="нативном Gemini-кандидате", require_two_faces=True)
            if problem:
                errors.append(problem)
                continue
            return output
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    raise RuntimeError("Gemini не вернул пригодный финальный кадр: " + " | ".join(errors[-3:])[:700])


async def _score_candidate(mod: Any, raw: bytes, user: bytes, ref: bytes, scene: str, label: str) -> dict[str, Any]:
    assessment = await previous._scene_assessment(mod, raw, scene, phase=label)
    if not assessment.get("hard_ok"):
        raise RuntimeError(str(assessment.get("reason") or "broken composition"))
    identity, reason = await previous._identity_similarity_qc(mod, raw, user, ref, scene)
    if identity <= 0:
        raise RuntimeError(reason)
    composition = float(assessment.get("total_score") or assessment.get("composition_score") or assessment.get("local_score") or 0)
    scene_score = float(assessment.get("scene_score") or 0)
    return {
        "total": round(identity * 0.84 + composition * 0.11 + scene_score * 0.05, 1),
        "identity": round(identity, 1),
        "scene": round(scene_score, 1),
        "label": label,
        "reason": reason,
        "output": raw,
    }


async def _run_native_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
) -> bytes:
    global _LAST_RUN_DEBUG
    if not user_photo or not celebrity_refs:
        raise RuntimeError("Отсутствует исходное селфи или референс выбранной персоны")
    best_ref = await impl._best_reference(celebrity_refs)
    debug: dict[str, Any] = {"models": _gemini_models(mod), "candidates": [], "errors": []}
    refs = _reference_parts(user_photo, celebrity_refs, best_ref, previous_result=previous_result)
    candidates: list[dict[str, Any]] = []
    early = _number("CELEBRITY_NATIVE_EARLY_ACCEPT_SCORE", 74.0, 50.0, 95.0)
    if _flag("CELEBRITY_NATIVE_GEMINI", True) and _gemini_key(mod):
        for index, model in enumerate(_gemini_models(mod)):
            try:
                raw = await _gemini_generate(mod, model, _native_prompt(celebrity_name, scene, index, refinement=bool(previous_result)), refs)
                row = await _score_candidate(mod, raw, user_photo, best_ref, scene, f"native-{model}")
                candidates.append(row)
                debug["candidates"].append({k: v for k, v in row.items() if k != "output"})
                if row["identity"] >= early:
                    debug["selected"] = {k: v for k, v in row.items() if k != "output"}
                    _LAST_RUN_DEBUG = debug
                    return row["output"]
            except Exception as exc:
                debug["errors"].append(f"{model}: {type(exc).__name__}: {exc}")
                log.warning("Native celebrity candidate %s failed: %s", model, exc)
    if candidates:
        candidates.sort(key=lambda item: item["total"], reverse=True)
        best = candidates[0]
        if (
            best["identity"] < _number("CELEBRITY_NATIVE_REPAIR_BELOW", 70.0, 45.0, 90.0)
            and _flag("CELEBRITY_NATIVE_PIAPI_REPAIR", True)
            and bool(_runtime_value(mod, "PIAPI_API_KEY"))
        ):
            try:
                repaired = await base._identity_lock(mod, user_photo, best_ref, best["output"])
                row = await _score_candidate(mod, repaired, user_photo, best_ref, scene, "native-piapi-repair")
                debug["candidates"].append({k: v for k, v in row.items() if k != "output"})
                if row["total"] > best["total"]:
                    best = row
            except Exception as exc:
                debug["errors"].append(f"piapi-repair: {type(exc).__name__}: {exc}")
        debug["selected"] = {k: v for k, v in best.items() if k != "output"}
        _LAST_RUN_DEBUG = debug
        return best["output"]
    if _flag("CELEBRITY_NATIVE_LEGACY_FALLBACK", True):
        try:
            output = await _LEGACY_RUN(mod, user_photo, celebrity_refs, celebrity_name, scene, previous_result=previous_result)
            debug["selected"] = {"label": "legacy-v134-fallback"}
            _LAST_RUN_DEBUG = debug
            return output
        except Exception as exc:
            debug["errors"].append(f"legacy-v134: {type(exc).__name__}: {exc}")
    _LAST_RUN_DEBUG = debug
    raise RuntimeError("Нативная генерация Gemini 3 не дала проверенный результат. " + " | ".join(debug["errors"][-6:])[:1400])


def _failure_kb():
    return v133._failure_kb()


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Откройте режим заново.")
        return
    now = time.monotonic()
    if str(session.get("state") or "") in {"queued", "generating"} and now - float(session.get("generation_started_monotonic") or 0) < 1200:
        await update.effective_message.reply_text("⏳ Эта генерация уже выполняется. Дождитесь результата.")
        return
    user_photo = engine._read_path(session.get("user_photo_path"))
    refs = [raw for raw in (engine._read_path(path) for path in engine._reference_paths(session)) if raw]
    scene = str(session.get("scene") or "").strip()
    celebrity_name = str(session.get("celebrity_name") or "выбранный человек").strip()
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
        if not base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            return False
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Уточняю оба лица в готовом кадре через Gemini 3…" if refinement else
            f"⏳ Создаю цельное селфи с {celebrity_name} напрямую через Gemini 3 Pro, проверяю оба лица и при необходимости запускаю резерв. Обычно 1–5 минут."
        )
        try:
            output = await _run_native_generation(mod, user_photo, refs, celebrity_name, scene, previous_result=previous_result)
        except Exception as exc:
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "result" if previous_result else "await_scene"
                session["last_generation_error"] = str(exc)[:2000]
                session["last_generation_failed_at"] = time.time()
                session["generation_failures"] = int(session.get("generation_failures") or 0) + 1
                session.pop("generation_id", None)
                await update.effective_message.reply_text(
                    "❌ Проверенный результат не получен, поэтому изображение не отправлено. "
                    + base_guard._public_failure(exc)
                    + ". Можно повторить сцену или выбрать другую.",
                    reply_markup=_failure_kb(),
                )
            return False
        if not base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            if str(session.get("generation_id") or "") == generation_id:
                session.pop("generation_id", None)
            return False
        session["result_path"] = engine._store_image(session, "result_refined.png" if refinement else "result.png", output)
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
            "Качество: Gemini 3 native identity, единый кадр и проверка сходства двух лиц.\n"
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
    cost = float(os.environ.get("CELEBRITY_NATIVE_UNIT_COST_USD") or getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.30) or 0.30)
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind="celebrity_selfie_gemini3_refine" if refinement else "celebrity_selfie_gemini3",
        remember_payload={"celebrity": celebrity_name, "scene": scene[:500], "refinement": refinement, "generation_id": generation_id, "pipeline": VERSION, "models": _gemini_models(mod)},
    )


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    session = engine._session(context, create=False)
    mod = engine._runtime_module()
    debug = _LAST_RUN_DEBUG or {}
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if base.impl.previous._active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        "pipeline=native_multi_reference\n"
        f"gemini_key={'ready' if (mod is not None and bool(_gemini_key(mod))) else 'missing'}\n"
        f"gemini_models={','.join(_gemini_models(mod)) if mod is not None else '-'}\n"
        "primary=gemini-3-pro-image\n"
        "fallback=gemini-3.1-flash-image\n"
        "face_swap=selective_repair_only\n"
        "legacy_v134=last_resort\n"
        "hard_gates=single_frame+two_people+no_collage\n"
        "failed_job_status=false\n"
        f"native_candidates={len(debug.get('candidates') or [])}\n"
        f"native_selected={debug.get('selected') or '-'}\n"
        f"native_errors={' | '.join(str(item) for item in (debug.get('errors') or [])[-3:])[:800] or '-'}\n"
        f"last_error={(session.get('last_generation_error') or '-')[:700] if session else '-'}"
    )
    raise ApplicationHandlerStop


v133._run_best_of_n_generation = _run_native_generation
v133._generate = _generate
previous._run_face_first_generation = _run_native_generation
base._run_validated_generation = _run_native_generation
base.impl._run_quality_generation = _run_native_generation
engine._run_multi_reference_generation = _run_native_generation
engine._generate = _generate
base.impl._diag = _diag

install_builder_hook = previous.install_builder_hook

__all__ = [
    "VERSION", "install_builder_hook", "_gemini_models", "_native_prompt", "_reference_parts",
    "_gemini_payload", "_gemini_images", "_gemini_generate", "_score_candidate",
    "_run_native_generation", "_generate", "_diag",
]
