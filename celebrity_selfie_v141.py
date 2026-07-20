# -*- coding: utf-8 -*-
"""Celebrity Selfie v141: accepted-result refinement and texture cleanup.

This overlay leaves v140's scene-first generation intact and fixes the post-result
workflow observed in production:

* the last file actually delivered to the user becomes the immutable refinement
  base; raw selfies and intermediate scene plates are never reused by an
  improvement action;
* similarity refinement edits only one selected face and rejects candidates that
  change the scene, damage the other identity, or reduce the target score;
* quality cleanup removes grain/moire/over-sharpening separately from identity
  work and is guarded against face drift;
* automatic weak-side repair is less aggressive and is rejected when it adds
  texture artifacts or changes the accepted composition;
* every accepted result has history, before/after metrics, an undo action, and
  dedicated diagnostics.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import ui_selfie_v138 as ui138

VERSION = "v141-accepted-result-targeted-refinement-2026-07-20"
_GROUP = -2_100_000_400
_BUILDER_FLAG = "_celebrity_selfie_v141_builder"
_HANDLER_FLAG = "_celebrity_selfie_v141_handlers"

_ORIGINAL_GENERATE = v139._generate
_ORIGINAL_REPAIR_WEAK_SIDE = v139._repair_weak_side
_ORIGINAL_RESULT_KB = v139.selfie.engine._result_kb


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


def _safe_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_file() else None


def _read_path(value: Any) -> bytes:
    path = _safe_path(value)
    return path.read_bytes() if path else b""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16] if raw else "-"


def _session(context: Any) -> dict[str, Any]:
    value = v139.selfie.engine._session(context, create=False)
    return value if isinstance(value, dict) else {}


def _accepted_bytes(session: dict[str, Any]) -> tuple[bytes, str]:
    for key in ("accepted_result_path", "result_path"):
        raw = _read_path(session.get(key))
        if raw:
            return raw, key
    return b"", ""


def _snapshot_accepted(session: dict[str, Any]) -> bool:
    # A fresh full generation must always replace an older accepted snapshot.
    # Prefer result_path explicitly; accepted_result_path is only a fallback for
    # sessions created before v141.
    raw = _read_path(session.get("result_path"))
    source_key = "result_path"
    if not raw:
        raw, source_key = _accepted_bytes(session)
    if not raw:
        return False
    path = str(session.get(source_key) or "")
    selected = dict(((session.get("v139_debug") or {}).get("selected") or {}))
    session.update({
        "accepted_result_path": path,
        "accepted_result_sha": _sha(raw),
        "accepted_scene": str(session.get("scene") or ""),
        "accepted_celebrity_name": str(
            session.get("celebrity_name")
            or session.get("selected_celebrity_name")
            or ""
        ),
        "accepted_selected": selected,
        "accepted_at": time.time(),
    })
    return True


def _button_text(query: Any) -> str:
    data = str(getattr(query, "data", "") or "")
    markup = getattr(getattr(query, "message", None), "reply_markup", None)
    for row in getattr(markup, "inline_keyboard", None) or []:
        for button in row:
            if str(getattr(button, "callback_data", "") or "") == data:
                return str(getattr(button, "text", "") or "")
    return ""


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def _result_kb(has_selected: bool):
    """Add explicit refinement actions and remove the legacy generic refine row."""
    from telegram import InlineKeyboardMarkup

    base = _ORIGINAL_RESULT_KB(has_selected)
    rows = [
        [ui138._inline_button("Улучшить сходство", "cs141:similarity", primary=True)],
        [ui138._inline_button("Убрать рябь / улучшить качество", "cs141:quality")],
        [
            ui138._inline_button("Усилить моё лицо", "cs141:user"),
            ui138._inline_button("Усилить лицо знаменитости", "cs141:celebrity"),
        ],
        [ui138._inline_button("Вернуть предыдущий результат", "cs141:undo")],
    ]
    for row in getattr(base, "inline_keyboard", None) or []:
        filtered = []
        for button in row:
            text = _norm(getattr(button, "text", ""))
            if "улучшить" in text and "сходств" in text:
                continue
            filtered.append(button)
        if filtered:
            rows.append(filtered)
    return InlineKeyboardMarkup(rows)


def _open_rgb(raw: bytes) -> Image.Image:
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode(image: Image.Image, quality: int = 96) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _face_boxes(raw: bytes) -> list[dict[str, Any]]:
    with contextlib.suppress(Exception):
        boxes = v139.selfie.base._face_boxes(raw)
        return [dict(item) for item in (boxes or []) if isinstance(item, dict)]
    return []


def _expanded_box(box: dict[str, Any], size: tuple[int, int], scale: float = 1.65) -> tuple[int, int, int, int]:
    width, height = size
    x = float(box.get("x") or 0)
    y = float(box.get("y") or 0)
    w = max(1.0, float(box.get("w") or 1))
    h = max(1.0, float(box.get("h") or 1))
    cx = x + w / 2.0
    cy = y + h / 2.0
    bw = w * scale
    bh = h * scale * 1.12
    return (
        max(0, int(cx - bw / 2)),
        max(0, int(cy - bh / 2)),
        min(width, int(cx + bw / 2)),
        min(height, int(cy + bh / 2)),
    )


def _perceptual_similarity(base: bytes, candidate: bytes, *, mask_faces: bool = True) -> float:
    """Coarse 0..1 composition lock; large scene changes fail decisively."""
    try:
        a = _open_rgb(base)
        b = _open_rgb(candidate).resize(a.size, Image.Resampling.LANCZOS)
        if mask_faces:
            for box in _face_boxes(base):
                area = _expanded_box(box, a.size, 1.8)
                neutral = Image.new("RGB", (area[2] - area[0], area[3] - area[1]), (128, 128, 128))
                a.paste(neutral, area[:2])
                b.paste(neutral, area[:2])
        a = ImageOps.fit(a.convert("L"), (160, 160), method=Image.Resampling.LANCZOS)
        b = ImageOps.fit(b.convert("L"), (160, 160), method=Image.Resampling.LANCZOS)
        mean = float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0])
        return round(max(0.0, min(1.0, 1.0 - mean / 255.0)), 4)
    except Exception:
        return 0.0


def _artifact_metrics(raw: bytes) -> dict[str, float]:
    """Relative high-frequency artifact metric used for before/after safeguards."""
    try:
        image = _open_rgb(raw)
        boxes = _face_boxes(raw)
        regions: list[Image.Image] = []
        if boxes:
            for box in sorted(boxes, key=lambda item: float(item.get("x") or 0))[:2]:
                area = _expanded_box(box, image.size, 1.35)
                if area[2] - area[0] >= 48 and area[3] - area[1] >= 48:
                    regions.append(image.crop(area))
        if not regions:
            w, h = image.size
            regions = [image.crop((int(w * 0.12), int(h * 0.06), int(w * 0.88), int(h * 0.72)))]
        noise_values: list[float] = []
        edge_values: list[float] = []
        for region in regions:
            gray = ImageOps.fit(region.convert("L"), (512, 512), method=Image.Resampling.LANCZOS)
            median = gray.filter(ImageFilter.MedianFilter(3))
            noise_values.append(float(ImageStat.Stat(ImageChops.difference(gray, median)).mean[0]))
            edge_values.append(float(ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]))
        noise = sum(noise_values) / len(noise_values)
        edge = sum(edge_values) / len(edge_values)
        quality = max(0.0, min(100.0, 100.0 - noise * 4.2 - max(0.0, edge - 32.0) * 0.9))
        return {"noise": round(noise, 2), "edge": round(edge, 2), "quality": round(quality, 1)}
    except Exception:
        return {"noise": 99.0, "edge": 99.0, "quality": 0.0}


def _local_cleanup(raw: bytes) -> bytes:
    """Feathered low-strength denoise: no synthesis, no scene or identity changes."""
    image = _open_rgb(raw)
    globally_smoothed = image.filter(ImageFilter.MedianFilter(3))
    output = Image.blend(image, globally_smoothed, _number("CELEBRITY_V141_GLOBAL_DENOISE_BLEND", 0.08, 0.0, 0.25))
    boxes = _face_boxes(raw)
    if not boxes:
        return _encode(output)
    for box in sorted(boxes, key=lambda item: float(item.get("x") or 0))[:2]:
        area = _expanded_box(box, image.size, 1.45)
        crop = image.crop(area)
        cleaned = crop.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.GaussianBlur(0.22))
        blend = Image.blend(crop, cleaned, _number("CELEBRITY_V141_FACE_DENOISE_BLEND", 0.30, 0.05, 0.55))
        mask = Image.new("L", crop.size, 0)
        inner = (
            max(1, int(crop.width * 0.08)),
            max(1, int(crop.height * 0.08)),
            max(2, int(crop.width * 0.92)),
            max(2, int(crop.height * 0.92)),
        )
        from PIL import ImageDraw
        ImageDraw.Draw(mask).ellipse(inner, fill=235)
        mask = mask.filter(ImageFilter.GaussianBlur(max(6.0, min(crop.size) * 0.08)))
        output.paste(blend, area[:2], mask)
    return _encode(output)


def _quality_cleanup_prompt() -> str:
    return (
        "Edit the FIRST image only. Perform conservative photographic restoration only: remove digital grain, moire, "
        "checkerboard texture, ringing, patch seams and excessive sharpening. Preserve the exact same scene, yacht/car/room, "
        "camera position, crop, pose, bodies, clothing, hands, lighting, hair, beard and BOTH facial identities. Do not "
        "reconstruct, beautify, de-age, relight, reshape, move or replace either face. Do not add or remove people or objects. "
        "Keep natural pores and realistic smartphone detail. Return the same photograph with cleaner texture only."
    )


def _targeted_prompt(side: str, label: str) -> str:
    side_up = side.upper()
    other = "RIGHT" if side == "left" else "LEFT"
    return (
        f"Edit the FIRST image only. This is a locked accepted photograph. Improve ONLY the {side_up} foreground face so it "
        f"matches the following face-only references for {label}. Preserve the accepted scene and every pixel outside that "
        f"single face as closely as possible: camera, crop, background, bodies, clothing, hands, lighting and the {other} "
        "person must not change. Never reuse the reference photo's car, room, table, background, pose or clothing. Preserve "
        "real age, head shape, hairline, eye spacing, nose, lips, mouth, jaw, beard and natural asymmetry. Use subtle natural "
        "skin texture without grain, moire, over-sharpening or plastic smoothing. Do not blend the two identities. Return only "
        "the edited accepted photograph."
    )


async def _openai_targeted(mod: Any, base: bytes, refs: list[bytes], side: str, label: str, aspect: str) -> bytes:
    images: list[tuple[str, bytes]] = [("accepted-result.jpg", v139._jpeg(base))]
    for index, raw in enumerate(refs[:3], start=1):
        images.append((f"target-face-reference-{index}.jpg", v139._face_crop(raw, 1152)))
    return await v139.selfie._openai_edit(mod, _targeted_prompt(side, label), images, aspect=aspect)


async def _openai_cleanup(mod: Any, base: bytes, aspect: str) -> bytes:
    return await v139.selfie._openai_edit(
        mod,
        _quality_cleanup_prompt(),
        [("accepted-result.jpg", v139._jpeg(base))],
        aspect=aspect,
    )


async def _qc(mod: Any, raw: bytes, user_ref: bytes, celebrity_ref: bytes) -> dict[str, Any]:
    result = await v139._final_identity_qc(mod, raw, user_ref, celebrity_ref)
    return {
        "user": float(result.get("user") or 0),
        "celebrity": float(result.get("celebrity") or 0),
        "minimum": float(result.get("minimum") or 0),
        "weighted": float(result.get("weighted") or 0),
        "unknown": bool(result.get("unknown")),
        "reason": str(result.get("reason") or "")[:300],
    }


def _side_value(qc: dict[str, Any], side: str) -> float:
    return float(qc.get("user") if side == "left" else qc.get("celebrity") or 0)


def _other_value(qc: dict[str, Any], side: str) -> float:
    return float(qc.get("celebrity") if side == "left" else qc.get("user") or 0)


async def _evaluate(
    mod: Any,
    base: bytes,
    candidate: bytes,
    user_ref: bytes,
    celebrity_ref: bytes,
    before: dict[str, Any],
    *,
    action: str,
    side: str | None = None,
    provider: str,
) -> dict[str, Any]:
    problem = v140._soft_scene_problem(candidate, f"v141-{action}")
    if problem:
        return {"accepted": False, "provider": provider, "reason": problem}
    after = await _qc(mod, candidate, user_ref, celebrity_ref)
    scene_similarity = _perceptual_similarity(base, candidate, mask_faces=True)
    full_similarity = _perceptual_similarity(base, candidate, mask_faces=False)
    base_art = _artifact_metrics(base)
    candidate_art = _artifact_metrics(candidate)
    min_scene = _number(
        "CELEBRITY_V141_QUALITY_SCENE_SIMILARITY" if action == "quality" else "CELEBRITY_V141_FACE_SCENE_SIMILARITY",
        0.80 if action == "quality" else 0.70,
        0.45,
        0.98,
    )
    identity_tolerance = _number("CELEBRITY_V141_OTHER_IDENTITY_TOLERANCE", 6.0, 0.0, 20.0)
    accepted = scene_similarity >= min_scene
    reason = "ok"
    target_gain = 0.0
    other_drop = 0.0
    if action == "quality":
        user_drop = float(before.get("user") or 0) - float(after.get("user") or 0)
        celebrity_drop = float(before.get("celebrity") or 0) - float(after.get("celebrity") or 0)
        quality_gain = float(candidate_art.get("quality") or 0) - float(base_art.get("quality") or 0)
        accepted = accepted and user_drop <= identity_tolerance and celebrity_drop <= identity_tolerance
        min_quality_gain = _number("CELEBRITY_V141_MIN_QUALITY_GAIN", 0.5, -3.0, 20.0)
        if provider == "local":
            accepted = accepted and quality_gain >= min(-0.5, min_quality_gain)
        else:
            accepted = accepted and quality_gain >= min_quality_gain
        if not accepted:
            reason = f"quality safeguard: scene={scene_similarity:.3f} user_drop={user_drop:.1f} celebrity_drop={celebrity_drop:.1f} quality_gain={quality_gain:.1f}"
    else:
        assert side in {"left", "right"}
        target_gain = _side_value(after, side) - _side_value(before, side)
        other_drop = _other_value(before, side) - _other_value(after, side)
        min_gain = _number("CELEBRITY_V141_MIN_IDENTITY_GAIN", 1.0, -2.0, 15.0)
        quality_drop = float(base_art.get("quality") or 0) - float(candidate_art.get("quality") or 0)
        accepted = accepted and other_drop <= identity_tolerance
        accepted = accepted and quality_drop <= _number("CELEBRITY_V141_MAX_QUALITY_DROP", 7.0, 0.0, 25.0)
        if not before.get("unknown") and not after.get("unknown"):
            accepted = accepted and (target_gain >= min_gain or float(after.get("minimum") or 0) > float(before.get("minimum") or 0))
        else:
            accepted = accepted and float(after.get("minimum") or 0) >= float(before.get("minimum") or 0) - 2.0
        if not accepted:
            reason = f"identity safeguard: scene={scene_similarity:.3f} target_gain={target_gain:.1f} other_drop={other_drop:.1f} quality_drop={quality_drop:.1f}"
    total = (
        float(after.get("minimum") or 0) * 0.38
        + float(after.get("weighted") or 0) * 0.22
        + scene_similarity * 24.0
        + float(candidate_art.get("quality") or 0) * 0.16
    )
    return {
        "accepted": bool(accepted),
        "provider": provider,
        "reason": reason,
        "action": action,
        "side": side,
        "before": before,
        "after": after,
        "scene_similarity": scene_similarity,
        "full_similarity": full_similarity,
        "artifact_before": base_art,
        "artifact_after": candidate_art,
        "target_gain": round(target_gain, 1),
        "other_drop": round(other_drop, 1),
        "total": round(total, 2),
        "output": candidate,
    }


async def _targeted_candidates(
    mod: Any,
    base: bytes,
    refs: list[bytes],
    user_ref: bytes,
    celebrity_ref: bytes,
    before: dict[str, Any],
    side: str,
    label: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    providers = [
        item.strip().casefold()
        for item in str(os.environ.get("CELEBRITY_V141_REFINEMENT_PROVIDERS") or "openai,piapi").split(",")
        if item.strip()
    ]
    results: list[dict[str, Any]] = []
    for provider in providers:
        stage = {"provider": provider, "side": side, "status": "running", "started_at": time.time()}
        debug["stages"].append(stage)
        try:
            if provider == "openai":
                if not v139.selfie._openai_key(mod):
                    raise RuntimeError("OpenAI image key missing")
                raw = await _openai_targeted(mod, base, refs, side, label, aspect)
            elif provider == "piapi":
                if not v139.pi_identity._piapi_key(mod):
                    raise RuntimeError("PiAPI key missing")
                raw = await v139._piapi_single_face(mod, base, refs[0], side)
            else:
                continue
            evaluated = await _evaluate(
                mod, base, raw, user_ref, celebrity_ref, before,
                action="similarity", side=side, provider=provider,
            )
            stage.update({
                "status": "accepted" if evaluated.get("accepted") else "rejected",
                "duration_s": round(time.time() - stage["started_at"], 2),
                "scene_similarity": evaluated.get("scene_similarity"),
                "target_gain": evaluated.get("target_gain"),
                "reason": evaluated.get("reason"),
            })
            debug["candidates"].append({key: value for key, value in evaluated.items() if key != "output"})
            if evaluated.get("accepted"):
                results.append(evaluated)
                if float(evaluated.get("target_gain") or 0) >= _number("CELEBRITY_V141_STOP_GAIN", 6.0, 1.0, 30.0):
                    break
        except Exception as exc:
            stage.update({"status": "error", "duration_s": round(time.time() - stage["started_at"], 2), "error": v139._safe_error(exc)})
            debug["errors"].append({"provider": provider, "error": v139._safe_error(exc)})
    results.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
    return results


async def _quality_candidates(
    mod: Any,
    base: bytes,
    user_ref: bytes,
    celebrity_ref: bytes,
    before: dict[str, Any],
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    local = _local_cleanup(base)
    evaluated = await _evaluate(
        mod, base, local, user_ref, celebrity_ref, before,
        action="quality", provider="local", side=None,
    )
    debug["candidates"].append({key: value for key, value in evaluated.items() if key != "output"})
    if evaluated.get("accepted"):
        results.append(evaluated)
    if _flag("CELEBRITY_V141_OPENAI_QUALITY_CLEANUP", True) and v139.selfie._openai_key(mod):
        stage = {"provider": "openai", "side": None, "status": "running", "started_at": time.time()}
        debug["stages"].append(stage)
        try:
            raw = await _openai_cleanup(mod, base, aspect)
            evaluated = await _evaluate(
                mod, base, raw, user_ref, celebrity_ref, before,
                action="quality", provider="openai", side=None,
            )
            stage.update({
                "status": "accepted" if evaluated.get("accepted") else "rejected",
                "duration_s": round(time.time() - stage["started_at"], 2),
                "scene_similarity": evaluated.get("scene_similarity"),
                "reason": evaluated.get("reason"),
            })
            debug["candidates"].append({key: value for key, value in evaluated.items() if key != "output"})
            if evaluated.get("accepted"):
                results.append(evaluated)
        except Exception as exc:
            stage.update({"status": "error", "duration_s": round(time.time() - stage["started_at"], 2), "error": v139._safe_error(exc)})
            debug["errors"].append({"provider": "openai", "error": v139._safe_error(exc)})
    results.sort(key=lambda item: (float(item.get("artifact_after", {}).get("quality") or 0), float(item.get("total") or 0)), reverse=True)
    return results


def _history_push(session: dict[str, Any], base_path: str, metadata: dict[str, Any]) -> None:
    history = list(session.get("accepted_history") or [])
    history.append({"path": base_path, "metadata": metadata, "saved_at": time.time()})
    session["accepted_history"] = history[-4:]


async def _send_result(update: Any, session: dict[str, Any], raw: bytes, caption: str) -> None:
    from telegram import InputFile

    bio = BytesIO(raw)
    bio.name = "celebrity_selfie.jpg"
    markup = v139.selfie.engine._result_kb(bool(v139.selfie.engine._selected_entry(session)))
    if v139.selfie.engine._flag("CELEBRITY_SELFIE_SEND_AS_DOCUMENT", True):
        await update.effective_message.reply_document(InputFile(bio), caption=caption[:1024], reply_markup=markup)
    else:
        await update.effective_message.reply_photo(photo=raw, caption=caption[:1024], reply_markup=markup)


async def _postprocess(update: Any, context: Any, action: str) -> None:
    session = _session(context)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Откройте режим заново.")
        return
    if str(session.get("state") or "") in {"queued", "generating", "refining_v141"}:
        await update.effective_message.reply_text("⏳ Обработка уже выполняется. Дождитесь результата.")
        return
    if action == "undo":
        history = list(session.get("accepted_history") or [])
        while history:
            row = history.pop()
            raw = _read_path(row.get("path"))
            if raw:
                session["accepted_history"] = history
                session["accepted_result_path"] = row["path"]
                session["result_path"] = row["path"]
                session["accepted_result_sha"] = _sha(raw)
                metadata = dict(row.get("metadata") or {})
                for key in ("accepted_selected", "accepted_scene", "accepted_celebrity_name"):
                    if key in metadata:
                        session[key] = metadata[key]
                session["state"] = "result"
                await _send_result(update, session, raw, "↩️ Предыдущий принятый результат восстановлен. Сцена и лица возвращены без новой генерации.")
                return
        await update.effective_message.reply_text("Предыдущего сохранённого результата пока нет.")
        return

    base, source_key = _accepted_bytes(session)
    if not base:
        await update.effective_message.reply_text("Последний выданный результат не найден. Сначала создайте AI-селфи заново.")
        return
    base_path = str(session.get(source_key) or "")
    user_ref = _read_path(session.get("user_photo_path"))
    second_user = _read_path(session.get("user_photo_2_path"))
    user_refs = [raw for raw in (user_ref, second_user) if raw]
    celebrity_refs = [raw for raw in (v139.selfie.engine._read_path(path) for path in v139.selfie.engine._reference_paths(session)) if raw]
    if not user_refs or not celebrity_refs:
        await update.effective_message.reply_text("Референсы лиц не найдены. Создайте результат заново из режима «Селфи со звездой».")
        return
    mod = v139.selfie.engine._runtime_module()
    if mod is None:
        await update.effective_message.reply_text("Сервис ещё загружается. Повторите через несколько секунд.")
        return
    aspect = v139.selfie._aspect_for_scene(str(session.get("accepted_scene") or session.get("scene") or ""))
    celebrity_name = str(session.get("accepted_celebrity_name") or session.get("celebrity_name") or session.get("selected_celebrity_name") or "выбранный человек")
    run_id = uuid.uuid4().hex[:12]
    debug: dict[str, Any] = {
        "version": VERSION,
        "run_id": run_id,
        "action": action,
        "base_path": base_path,
        "base_sha": _sha(base),
        "scene_locked": str(session.get("accepted_scene") or session.get("scene") or ""),
        "celebrity_locked": celebrity_name,
        "stages": [],
        "candidates": [],
        "errors": [],
        "selected": None,
        "started_at": time.time(),
    }
    session["state"] = "refining_v141"
    session["v141_debug"] = debug

    labels = {
        "similarity": "точечно улучшаю более слабое лицо в последнем выданном кадре",
        "user": "точечно улучшаю только ваше лицо в последнем выданном кадре",
        "celebrity": "точечно улучшаю только лицо выбранного человека",
        "quality": "убираю рябь, шум и чрезмерную резкость без смены сцены и лиц",
    }
    await update.effective_message.reply_text(f"⏳ {labels.get(action, 'улучшаю последний результат')}. Сцена зафиксирована и не будет создаваться заново.")

    async def work() -> bool:
        try:
            before = await _qc(mod, base, user_refs[0], celebrity_refs[0])
            debug["before"] = before
            if action == "quality":
                candidates = await _quality_candidates(mod, base, user_refs[0], celebrity_refs[0], before, aspect, debug)
            else:
                if action == "user":
                    side = "left"
                elif action == "celebrity":
                    side = "right"
                else:
                    side = "left" if float(before.get("user") or 0) <= float(before.get("celebrity") or 0) else "right"
                refs = user_refs if side == "left" else celebrity_refs
                label = "the USER" if side == "left" else f"the selected PUBLIC PERSON ({celebrity_name})"
                debug["target_side"] = side
                candidates = await _targeted_candidates(
                    mod, base, refs, user_refs[0], celebrity_refs[0], before,
                    side, label, aspect, debug,
                )
            if not candidates:
                debug["finished_at"] = time.time()
                debug["decision"] = "kept_original_no_safe_improvement"
                session["v141_debug"] = debug
                session["state"] = "result"
                await update.effective_message.reply_text(
                    "🛡 Последний результат сохранён без изменений: новые варианты либо не улучшили сходство/текстуру, "
                    "либо затронули сцену или второе лицо. Кредиты за невыданное улучшение не должны списываться.",
                    reply_markup=v139.selfie.engine._result_kb(bool(v139.selfie.engine._selected_entry(session))),
                )
                return False
            selected = candidates[0]
            output = selected["output"]
            debug["selected"] = {key: value for key, value in selected.items() if key != "output"}
            debug["after"] = selected.get("after")
            debug["finished_at"] = time.time()
            debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
            debug["decision"] = "accepted"
            _history_push(session, base_path, {
                "accepted_result_sha": session.get("accepted_result_sha"),
                "accepted_selected": session.get("accepted_selected"),
                "accepted_scene": session.get("accepted_scene"),
                "accepted_celebrity_name": session.get("accepted_celebrity_name"),
            })
            filename = f"result_v141_{action}_{int(time.time())}.jpg"
            new_path = v139.selfie.engine._store_image(session, filename, output)
            session.update({
                "result_path": new_path,
                "accepted_result_path": new_path,
                "accepted_result_sha": _sha(output),
                "accepted_scene": debug["scene_locked"],
                "accepted_celebrity_name": celebrity_name,
                "accepted_selected": selected.get("after") or {},
                "accepted_at": time.time(),
                "v141_debug": debug,
                "state": "result",
                "last_generation_ok_at": time.time(),
            })
            after = selected.get("after") or {}
            art = selected.get("artifact_after") or {}
            if action == "quality":
                summary = (
                    f"✨ Качество улучшено без перестройки сцены. Текстурная оценка: "
                    f"{float((selected.get('artifact_before') or {}).get('quality') or 0):.0f} → {float(art.get('quality') or 0):.0f}/100."
                )
            else:
                target = "вашего лица" if selected.get("side") == "left" else "лица выбранного человека"
                summary = (
                    f"🔁 Сходство {target} улучшено. Минимальная оценка двух лиц: "
                    f"{float(before.get('minimum') or 0):.0f} → {float(after.get('minimum') or 0):.0f}/100."
                )
            caption = (
                f"{summary}\n"
                f"Сцена зафиксирована: {debug['scene_locked'] or 'исходная сцена'}.\n"
                f"Контроль композиции: {float(selected.get('scene_similarity') or 0) * 100:.0f}/100.\n"
                "Пометка: изображение создано ИИ и не подтверждает реальную встречу, поддержку или партнёрство."
            )
            await _send_result(update, session, output, caption)
            return True
        except Exception as exc:
            debug["errors"].append({"provider": "pipeline", "error": v139._safe_error(exc)})
            debug["finished_at"] = time.time()
            debug["decision"] = "error_kept_original"
            session["v141_debug"] = debug
            session["state"] = "result"
            await update.effective_message.reply_text(
                f"❌ Улучшение не применено; исходный принятый кадр сохранён. Диагностика: {run_id}. "
                f"Причина: {v139._safe_error(exc)[:300]}"
            )
            return False

    pay = getattr(mod, "_try_pay_then_do", None)
    if not callable(pay):
        await work()
        return
    cost = _number(
        "CELEBRITY_V141_QUALITY_COST_USD" if action == "quality" else "CELEBRITY_V141_REFINEMENT_COST_USD",
        0.12 if action == "quality" else 0.25,
        0.0,
        5.0,
    )
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind=f"celebrity_selfie_v141_{action}",
        remember_payload={
            "action": action,
            "run_id": run_id,
            "pipeline": VERSION,
            "base_sha": debug["base_sha"],
            "scene_locked": debug["scene_locked"],
        },
    )
    if session.get("state") == "refining_v141":
        session["state"] = "result"


async def _callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(getattr(query, "data", "") or "")
    text = _norm(_button_text(query))
    action = ""
    if data.startswith("cs141:"):
        action = data.split(":", 1)[1]
    elif "улучшить" in text and "сходств" in text:
        # Old result messages survive deployments. Route their legacy button to
        # the accepted-result v141 action instead of the old scene rebuild.
        action = "similarity"
    if action not in {"similarity", "quality", "user", "celebrity", "undo"}:
        return
    with contextlib.suppress(Exception):
        await query.answer()
    await _postprocess(update, context, action)
    raise ApplicationHandlerStop


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    """Run v140 normally, then freeze the exact file that was delivered."""
    # Legacy refinement callbacks are intercepted by _callback. If one still
    # reaches this function, never let it rebuild from the raw selfie.
    if refinement:
        await _postprocess(update, context, "similarity")
        return
    await _ORIGINAL_GENERATE(update, context, refinement=False)
    session = _session(context)
    if session.get("state") == "result" and session.get("result_path"):
        _snapshot_accepted(session)


async def _guarded_auto_repair(
    mod: Any,
    best: dict[str, Any],
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> dict[str, Any]:
    """Avoid a second aggressive face pass unless the identity is genuinely weak."""
    threshold = _number("CELEBRITY_V141_AUTO_REPAIR_BELOW", 58.0, 35.0, 85.0)
    if float(best.get("identity_min") or 0) >= threshold:
        best["auto_repair"] = "skipped_above_v141_threshold"
        return best
    repaired = await _ORIGINAL_REPAIR_WEAK_SIDE(mod, best, user_refs, celebrity_refs, celebrity_name, aspect, debug)
    if repaired is best or repaired.get("output") == best.get("output"):
        return best
    scene_similarity = _perceptual_similarity(best["output"], repaired["output"], mask_faces=True)
    before_art = _artifact_metrics(best["output"])
    after_art = _artifact_metrics(repaired["output"])
    identity_gain = float(repaired.get("identity_min") or 0) - float(best.get("identity_min") or 0)
    if (
        scene_similarity < _number("CELEBRITY_V141_AUTO_REPAIR_SCENE_SIMILARITY", 0.72, 0.45, 0.98)
        or float(after_art.get("quality") or 0) < float(before_art.get("quality") or 0) - _number("CELEBRITY_V141_AUTO_REPAIR_MAX_QUALITY_DROP", 5.0, 0.0, 20.0)
        or identity_gain < _number("CELEBRITY_V141_AUTO_REPAIR_MIN_GAIN", 1.0, -2.0, 15.0)
    ):
        best["auto_repair"] = "rejected_by_v141_safeguard"
        best["auto_repair_scene_similarity"] = scene_similarity
        best["auto_repair_identity_gain"] = round(identity_gain, 1)
        return best
    repaired["auto_repair"] = "accepted_by_v141_safeguard"
    repaired["auto_repair_scene_similarity"] = scene_similarity
    repaired["auto_repair_identity_gain"] = round(identity_gain, 1)
    return repaired


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = _session(context)
    debug = session.get("v141_debug") or {}
    base_debug = session.get("v139_debug") or v139._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "refinement_base=last_delivered_accepted_result_only",
        "scene_lock=required",
        "raw_selfie_as_refinement_base=disabled",
        "actions=similarity+quality+user_face+celebrity_face+undo",
        f"identity_providers={os.environ.get('CELEBRITY_V139_IDENTITY_PROVIDERS', '-')}",
        f"refinement_providers={os.environ.get('CELEBRITY_V141_REFINEMENT_PROVIDERS', 'openai,piapi')}",
        f"auto_repair_below={_number('CELEBRITY_V141_AUTO_REPAIR_BELOW', 58, 35, 85):.0f}",
        f"accepted_path={session.get('accepted_result_path') or '-'}",
        f"accepted_sha={session.get('accepted_result_sha') or '-'}",
        f"accepted_scene={session.get('accepted_scene') or '-'}",
        f"history={len(session.get('accepted_history') or [])}",
        f"last_action={debug.get('action') or '-'}",
        f"run_id={debug.get('run_id') or base_debug.get('run_id') or '-'}",
        f"decision={debug.get('decision') or '-'}",
        f"target_side={debug.get('target_side') or '-'}",
        f"before={str(debug.get('before') or '-')[:650]}",
        f"after={str(debug.get('after') or '-')[:650]}",
        f"selected={str(selected or '-')[:850]}",
        f"base_pipeline={base_debug.get('version') or v140.VERSION}",
        f"base_failure={base_debug.get('failure_class') or '-'}",
    ]
    if debug.get("stages"):
        lines.append("refinement_stages:")
        for stage in debug.get("stages", [])[-6:]:
            lines.append(
                f"- {stage.get('provider')} {stage.get('side') or '-'} {stage.get('status')} "
                f"scene={stage.get('scene_similarity', '-')} gain={stage.get('target_gain', '-')} "
                f"error={str(stage.get('error') or '')[:180]}"
            )
    if debug.get("errors"):
        lines.append("refinement_errors:")
        for error in debug.get("errors", [])[-4:]:
            lines.append(f"- {error.get('provider')}: {str(error.get('error') or '')[:260]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    # OpenAI high-fidelity edit produces cleaner identity locks than PiAPI in the
    # observed noisy output. PiAPI remains a fallback. An explicit Render value
    # may override this with CELEBRITY_V141_IDENTITY_PROVIDERS.
    os.environ["CELEBRITY_V139_IDENTITY_PROVIDERS"] = str(
        os.environ.get("CELEBRITY_V141_IDENTITY_PROVIDERS") or "openai,piapi"
    )
    os.environ.setdefault("CELEBRITY_V141_REFINEMENT_PROVIDERS", "openai,piapi")
    os.environ.setdefault("CELEBRITY_V141_AUTO_REPAIR_BELOW", "58")
    os.environ.setdefault("CELEBRITY_V141_REFINEMENT_COST_USD", "0.25")
    os.environ.setdefault("CELEBRITY_V141_QUALITY_COST_USD", "0.12")
    os.environ.setdefault("CELEBRITY_V141_OPENAI_QUALITY_CLEANUP", "1")

    v139._repair_weak_side = _guarded_auto_repair
    v139._generate = _generate
    v139.selfie._generate = _generate
    v139.selfie.engine._generate = _generate
    v139.selfie.engine._result_kb = _result_kb


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
            for command in ("diag_selfie_v141", "diag_selfie_v139", "diag_celebrity_flow", "diag_brand"):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


install()

__all__ = [
    "VERSION", "install", "install_builder_hook", "_result_kb", "_generate",
    "_postprocess", "_guarded_auto_repair", "_local_cleanup", "_artifact_metrics",
    "_perceptual_similarity", "_evaluate", "_diag",
]
