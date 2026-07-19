# -*- coding: utf-8 -*-
"""Celebrity Selfie v134: face-first quality with soft scene/background scoring.

v133 generated multiple candidates but treated scene recognition as a hard gate twice.
That rejected otherwise usable, identity-preserving selfies after face lock. v134 keeps
hard structural safety checks (one frame, two people, no collage) while making the
background a soft ranking signal. Identity quality is the primary acceptance signal.
"""
from __future__ import annotations

import base64
import contextlib
import logging
import os
from io import BytesIO
from typing import Any

from PIL import Image, ImageChops, ImageOps, ImageStat

import celebrity_selfie_v133 as previous

VERSION = "v134-celebrity-selfie-face-first-soft-scene-2026-07-19"
base = previous.base
engine = previous.engine
impl = previous.impl
log = logging.getLogger("gpt-bot.celebrity-selfie-v134")

_LAST_RUN_DEBUG: dict[str, Any] = {}

for _module in (previous, base, base.previous, impl, engine, previous.base_guard):
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


def _scene_profile(scene: str) -> str:
    """Describe a preferred environment, never an identity-blocking hard contract."""
    low = str(scene or "").casefold().replace("ё", "е")
    if "красн" in low and "площад" in low:
        return (
            "Preferred environment: a realistic tourist smartphone selfie in Red Square, Moscow. "
            "One recognisable landmark is sufficient: Saint Basil's Cathedral OR the Kremlin/Spasskaya Tower. "
            "The two faces are more important than a wide postcard view; keep the background plausible and coherent."
        )
    if "яхт" in low or "море" in low:
        return (
            "Preferred environment: one modern yacht deck or marina setting with a coherent horizon and railings. "
            "Do not sacrifice clear, natural faces merely to show the whole vessel."
        )
    if "ресторан" in low:
        return (
            "Preferred environment: one modern restaurant or lounge with a shared table and warm practical lighting. "
            "The background may be understated; both faces must remain clear and natural."
        )
    if "премьер" in low or "дорожк" in low:
        return (
            "Preferred environment: one film-premiere or red-carpet setting with evening flash atmosphere. "
            "A subtle event background is enough; no readable sponsor text is required."
        )
    if "выстав" in low or "антик" in low:
        return (
            "Preferred environment: one public exhibition, gallery or antiques venue with coherent displays. "
            "The venue is secondary to accurate, unobstructed faces."
        )
    requested = str(scene or "natural public location").strip()
    return (
        f"Preferred environment: {requested}. Keep it coherent and plausible, but prioritise the two faces over exact "
        "background detail."
    )


def _scene_prompt(celebrity_name: str, scene: str, variant: int) -> str:
    rescue = int(variant) >= 90
    framings = (
        "arm-length smartphone selfie, heads and upper torsos visible",
        "friendly shoulder-to-shoulder medium selfie, equal eye line",
        "slightly wider vertical smartphone selfie, both faces large and unobstructed",
    )
    framing = framings[int(variant) % len(framings)]
    rescue_note = (
        "RESCUE PASS: use a slightly wider composition so one recognisable environmental cue remains visible behind "
        "the pair, while keeping both faces large. "
        if rescue else ""
    )
    return (
        "Create exactly ONE seamless photorealistic vertical smartphone photograph in ONE continuous camera frame. "
        "Never create a collage, diptych, split screen, before/after, contact sheet, reference board, border or divider. "
        "Exactly TWO main adults are physically together: placeholder A on the LEFT and placeholder B on the RIGHT. "
        f"Placeholder B should only have the broad age/build of {celebrity_name}; precise identity is added later. "
        "FACE-FIRST PRIORITY: both faces must be frontal or gentle 3/4, upright, unobstructed, similarly sized, sharply "
        "visible, naturally lit and separated enough for a later two-face swap. Identity-ready faces matter more than "
        "perfect landmark detail. Do not copy supplied reference backgrounds, clothes, tables, walls or objects. "
        "No third foreground person, duplicate body, extra face, poster portrait, phone-screen portrait, text or watermark. "
        f"Composition: {framing}. {rescue_note}{_scene_profile(scene)} "
        "Natural skin texture, coherent lighting and perspective, realistic anatomy, portrait 4:5. Return only the image."
    )


def _background_preservation_score(before: bytes, after: bytes) -> float:
    """Coarse 0..100 score from outer-frame regions, where face lock should not change the scene."""
    try:
        a = ImageOps.fit(base._open_rgb(before).convert("L"), (480, 600), method=Image.Resampling.LANCZOS)
        b = ImageOps.fit(base._open_rgb(after).convert("L"), (480, 600), method=Image.Resampling.LANCZOS)
        regions = (
            (0, 0, 480, 120),
            (0, 120, 72, 510),
            (408, 120, 480, 510),
            (0, 510, 480, 600),
        )
        weighted_sum = 0.0
        pixels = 0
        for box in regions:
            ca = a.crop(box)
            cb = b.crop(box)
            diff = ImageChops.difference(ca, cb)
            mean = float(ImageStat.Stat(diff).mean[0])
            count = ca.width * ca.height
            weighted_sum += mean * count
            pixels += count
        mean_diff = weighted_sum / max(1, pixels)
        return max(0.0, min(100.0, 100.0 - mean_diff / 2.55))
    except Exception as exc:
        log.info("Background preservation score unavailable: %s", exc)
        return 55.0


async def _scene_assessment(mod: Any, raw: bytes, scene: str, *, phase: str) -> dict[str, Any]:
    """Return hard structural checks plus soft environment scores.

    Scene mismatch is intentionally never a hard rejection. Only broken composition
    (split screen / wrong foreground count) is hard-fail.
    """
    local = previous._candidate_local_score(raw)
    result: dict[str, Any] = {
        "phase": phase,
        "hard_ok": local > 0,
        "local_score": round(local, 1),
        "scene_score": 55.0,
        "composition_score": local,
        "face_swap_readiness": local,
        "landmark_visible": False,
        "reason": "local",
    }
    if local <= 0:
        result["reason"] = "local structural rejection"
        return result

    vision = getattr(mod, "ask_openai_vision", None)
    if not _flag("CELEBRITY_VISION_RANKING", True) or not callable(vision):
        return result

    prompt = (
        "Evaluate this two-person smartphone selfie candidate. Do not identify anyone. Return strict JSON with keys: "
        "single_scene boolean, split_screen boolean, foreground_people integer, composition_score integer 0-100, "
        "face_swap_readiness integer 0-100, scene_score integer 0-100, landmark_visible boolean, reason short string. "
        "Scene score is only how well the environment resembles the request; do not mark the image structurally invalid "
        "just because the landmark is subtle. Exactly two foreground people and one continuous frame are mandatory. "
        f"Requested environment: {scene[:700]}"
    )
    try:
        answer = await vision(prompt, base64.b64encode(raw).decode("ascii"), "image/jpeg")
        data = previous._json_object(answer) or {}
        if data.get("single_scene") is False or data.get("split_screen") is True:
            result.update({"hard_ok": False, "reason": str(data.get("reason") or "split-screen")})
            return result
        people = data.get("foreground_people")
        if isinstance(people, (int, float)) and int(people) != 2:
            result.update({"hard_ok": False, "reason": f"foreground_people={int(people)}"})
            return result
        composition = float(data.get("composition_score") or local)
        readiness = float(data.get("face_swap_readiness") or local)
        scene_score = float(data.get("scene_score") or 45.0)
        total = local * 0.30 + composition * 0.35 + readiness * 0.30 + scene_score * 0.05
        result.update({
            "composition_score": round(composition, 1),
            "face_swap_readiness": round(readiness, 1),
            "scene_score": round(max(0.0, min(100.0, scene_score)), 1),
            "landmark_visible": bool(data.get("landmark_visible")),
            "total_score": round(max(0.0, min(100.0, total)), 1),
            "reason": str(data.get("reason") or "vision"),
        })
    except Exception as exc:
        result["reason"] = f"vision-error:{type(exc).__name__}"
        log.info("Soft scene assessment unavailable: %s", exc)
    return result


async def _identity_similarity_qc(
    mod: Any,
    output: bytes,
    user_photo: bytes,
    celebrity_ref: bytes,
    scene: str,
) -> tuple[float, str]:
    """Identity-only QC. Environment mismatch must never zero a good face match."""
    problem = base._image_problem(output, stage="финальном изображении", require_two_faces=True)
    if problem:
        return 0.0, problem
    vision = getattr(mod, "ask_openai_vision", None)
    if not _flag("CELEBRITY_IDENTITY_VISION_QC", True) or not callable(vision):
        return 72.0, "identity-vision-unavailable"

    user = ImageOps.fit(base._open_rgb(base._face_crop(user_photo, 512)), (512, 512), method=Image.Resampling.LANCZOS)
    celeb = ImageOps.fit(base._open_rgb(base._face_crop(celebrity_ref, 512)), (512, 512), method=Image.Resampling.LANCZOS)
    final = ImageOps.fit(base._open_rgb(output), (768, 512), method=Image.Resampling.LANCZOS)
    board = Image.new("RGB", (1792, 512), (24, 24, 24))
    board.paste(user, (0, 0))
    board.paste(celeb, (512, 0))
    board.paste(final, (1024, 0))
    board_raw = base._encode_jpeg(board, 92)
    prompt = (
        "This is a three-panel QA board: LEFT=user reference, MIDDLE=public-person reference, RIGHT=final selfie. "
        "Do not identify or name anyone. Ignore the background and compare facial identity only, allowing normal changes "
        "in expression, camera angle and lighting. Return strict JSON: user_similarity integer 0-100, "
        "celebrity_similarity integer 0-100, two_distinct_people boolean, reason short string."
    )
    try:
        answer = await vision(prompt, base64.b64encode(board_raw).decode("ascii"), "image/jpeg")
        data = previous._json_object(answer) or {}
        if not data:
            return 70.0, "identity-vision-unparsed"
        if data.get("two_distinct_people") is False:
            return 0.0, str(data.get("reason") or "identities blended")
        user_score = float(data.get("user_similarity") or 0)
        celeb_score = float(data.get("celebrity_similarity") or 0)
        minimum = min(user_score, celeb_score)
        threshold = _number("CELEBRITY_MIN_IDENTITY_SCORE", 52.0, 35.0, 90.0)
        if minimum < threshold:
            return 0.0, f"identity scores user={user_score:.0f}, celebrity={celeb_score:.0f}"
        weighted = user_score * 0.55 + celeb_score * 0.45
        return min(100.0, weighted), str(data.get("reason") or "identity-ok")
    except Exception as exc:
        log.info("Identity Vision QC unavailable: %s", exc)
        return 70.0, "identity-vision-error"


async def _run_face_first_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
) -> bytes:
    global _LAST_RUN_DEBUG
    if not user_photo:
        raise RuntimeError("Исходное селфи пользователя отсутствует")
    best_ref = await impl._best_reference(celebrity_refs)
    debug: dict[str, Any] = {"scene": scene[:200], "celebrity": celebrity_name, "drafts": [], "finals": [], "errors": []}

    if previous_result:
        output = await base._identity_lock(mod, user_photo, best_ref, previous_result)
        identity_score, reason = await _identity_similarity_qc(mod, output, user_photo, best_ref, scene)
        if identity_score <= 0:
            raise RuntimeError("Улучшение сходства отклонено: " + reason)
        final_scene = await _scene_assessment(mod, output, scene, phase="refinement")
        debug["finals"].append({"identity": round(identity_score, 1), "scene": final_scene})
        _LAST_RUN_DEBUG = debug
        return output

    candidate_count = _integer("CELEBRITY_SCENE_CANDIDATES", 3, 2, 4)
    identity_count = _integer("CELEBRITY_IDENTITY_CANDIDATES", 2, 1, candidate_count)
    user_crop = base._face_crop(user_photo, 768)
    celebrity_crop = base._face_crop(best_ref, 768)
    drafts: list[dict[str, Any]] = []

    async def add_comet(index: int) -> None:
        try:
            raw = await previous._comet_scene_candidate(mod, user_crop, celebrity_crop, celebrity_name, scene, index)
            assessment = await _scene_assessment(mod, raw, scene, phase=f"draft-{index + 1}")
            debug["drafts"].append(assessment)
            if assessment.get("hard_ok"):
                drafts.append({"score": float(assessment.get("total_score") or assessment.get("local_score") or 0), "raw": raw, "label": f"comet-{index + 1}", "assessment": assessment})
            else:
                debug["errors"].append(f"candidate {index + 1}: {assessment.get('reason')}")
        except Exception as exc:
            debug["errors"].append(f"candidate {index + 1}: {type(exc).__name__}: {exc}")

    import asyncio
    semaphore = asyncio.Semaphore(_integer("CELEBRITY_SCENE_PARALLEL", 2, 1, 3))

    async def limited(index: int) -> None:
        async with semaphore:
            await add_comet(index)

    await asyncio.gather(*(limited(index) for index in range(candidate_count)))

    if len(drafts) < identity_count and _flag("CELEBRITY_OPENAI_SCENE_FALLBACK", True):
        try:
            raw = await previous._openai_scene_candidate(mod, user_crop, celebrity_crop, celebrity_name, scene)
            assessment = await _scene_assessment(mod, raw, scene, phase="draft-openai")
            debug["drafts"].append(assessment)
            if assessment.get("hard_ok"):
                drafts.append({"score": float(assessment.get("total_score") or 0), "raw": raw, "label": "openai", "assessment": assessment})
            else:
                debug["errors"].append("OpenAI candidate: " + str(assessment.get("reason") or "structural rejection"))
        except Exception as exc:
            debug["errors"].append(f"OpenAI fallback: {type(exc).__name__}: {exc}")

    if not drafts:
        _LAST_RUN_DEBUG = debug
        raise RuntimeError("Не получено ни одной цельной сцены. " + " | ".join(debug["errors"][-6:])[:1100])

    drafts.sort(key=lambda item: item["score"], reverse=True)
    finals: list[dict[str, Any]] = []

    async def lock_and_score(item: dict[str, Any], *, rescue: bool = False) -> None:
        try:
            draft = item["raw"]
            output = await base._identity_lock(mod, user_photo, best_ref, draft)
            identity_score, identity_reason = await _identity_similarity_qc(mod, output, user_photo, best_ref, scene)
            if identity_score <= 0:
                raise RuntimeError(identity_reason)
            final_scene = await _scene_assessment(mod, output, scene, phase="final-rescue" if rescue else "final")
            if not final_scene.get("hard_ok"):
                raise RuntimeError(str(final_scene.get("reason") or "broken final composition"))
            bg_score = _background_preservation_score(draft, output)
            scene_score = float(final_scene.get("scene_score") or 0)
            total = identity_score * 0.78 + float(item["score"]) * 0.12 + scene_score * 0.05 + bg_score * 0.05
            row = {
                "total": round(total, 1),
                "identity": round(identity_score, 1),
                "scene": round(scene_score, 1),
                "background_preservation": round(bg_score, 1),
                "label": item["label"],
                "identity_reason": identity_reason,
                "output": output,
            }
            finals.append(row)
            debug["finals"].append({key: value for key, value in row.items() if key != "output"})
        except Exception as exc:
            debug["errors"].append(f"identity {item.get('label')}: {type(exc).__name__}: {exc}")

    for item in drafts[:identity_count]:
        await lock_and_score(item)

    if not finals:
        _LAST_RUN_DEBUG = debug
        raise RuntimeError(
            "Ни один кандидат не прошёл проверку двух лиц и целостности кадра. "
            + " | ".join(debug["errors"][-8:])[:1300]
        )

    finals.sort(key=lambda item: item["total"], reverse=True)
    best = finals[0]
    rescue_scene_below = _number("CELEBRITY_SCENE_RESCUE_BELOW", 42.0, 0.0, 90.0)
    rescue_bg_below = _number("CELEBRITY_BACKGROUND_RESCUE_BELOW", 48.0, 0.0, 90.0)
    needs_rescue = best["scene"] < rescue_scene_below or best["background_preservation"] < rescue_bg_below

    if needs_rescue and _flag("CELEBRITY_SCENE_RESCUE", True):
        try:
            raw = await previous._comet_scene_candidate(mod, user_crop, celebrity_crop, celebrity_name, scene, 97)
            assessment = await _scene_assessment(mod, raw, scene, phase="draft-rescue")
            debug["drafts"].append(assessment)
            if assessment.get("hard_ok"):
                rescue_item = {"score": float(assessment.get("total_score") or 0), "raw": raw, "label": "comet-rescue", "assessment": assessment}
                await lock_and_score(rescue_item, rescue=True)
                finals.sort(key=lambda item: item["total"], reverse=True)
                best = finals[0]
        except Exception as exc:
            debug["errors"].append(f"rescue: {type(exc).__name__}: {exc}")

    debug["selected"] = {key: value for key, value in best.items() if key != "output"}
    _LAST_RUN_DEBUG = debug
    return best["output"]


def _compact_debug() -> str:
    debug = _LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    errors = debug.get("errors") or []
    return (
        f"last_selected={selected or '-'}\n"
        f"draft_count={len(debug.get('drafts') or [])}\n"
        f"final_count={len(debug.get('finals') or [])}\n"
        f"debug_errors={' | '.join(str(item) for item in errors[-3:])[:700] or '-'}"
    )


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    session = engine._session(context, create=False)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        f"active={'yes' if base.impl.previous._active(context) else 'no'}\n"
        f"state={session.get('state', '-') if session else '-'}\n"
        f"owner={session.get('owner', '-') if session else '-'}\n"
        "catalog=30 (ru=20, us=10)\n"
        "quality_priority=identity_first\n"
        "scene_gate=soft_score_only\n"
        "hard_gates=single_frame+two_people+no_collage\n"
        "scene_rescue=enabled\n"
        "background_preservation=rank_only\n"
        f"scene_candidates={_integer('CELEBRITY_SCENE_CANDIDATES', 3, 2, 4)}\n"
        f"identity_candidates={_integer('CELEBRITY_IDENTITY_CANDIDATES', 2, 1, 4)}\n"
        "provider_chain=comet_best_of_n+openai_images_fallback+piapi_identity_lock\n"
        f"identity_engine={'ready' if bool(os.environ.get('PIAPI_API_KEY')) else 'missing'}\n"
        f"last_error={(session.get('last_generation_error') or '-')[:500] if session else '-'}\n"
        + _compact_debug()
    )
    raise ApplicationHandlerStop


# Rewire the already-audited v133 routing owner to the v134 scoring policy.
previous._scene_profile = _scene_profile
previous._scene_prompt = _scene_prompt
previous._identity_similarity_qc = _identity_similarity_qc
previous._run_best_of_n_generation = _run_face_first_generation
base._scene_prompt = _scene_prompt
base._run_validated_generation = _run_face_first_generation
base.impl._run_quality_generation = _run_face_first_generation
engine._run_multi_reference_generation = _run_face_first_generation
base.impl._diag = _diag

install_builder_hook = previous.install_builder_hook

__all__ = [
    "VERSION",
    "install_builder_hook",
    "_scene_profile",
    "_scene_prompt",
    "_background_preservation_score",
    "_scene_assessment",
    "_identity_similarity_qc",
    "_run_face_first_generation",
    "_diag",
]
