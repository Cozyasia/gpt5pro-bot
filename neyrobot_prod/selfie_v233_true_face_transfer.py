# -*- coding: utf-8 -*-
"""V233: keep V232/Gemini composition, replace synthetic identity pass with true FaceSwap.

The stable V232 stage-1 remains untouched. After Gemini creates the two-person scene,
PERSON A's real face is transferred from one of the user's original photos using the
already proven FaceSwap providers in main.py. Segmind v2 is preferred because it
supports an explicit target-face index; PiAPI is the fallback. Only the selected
PERSON-A facial region is composited back into the untouched Gemini frame so the
hero, body, hands, clothing, background and framing remain unchanged.
"""
from __future__ import annotations

import contextlib
from typing import Any

VERSION = "v233-v232-gemini-true-face-transfer-2026-08-17"


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    return v229._runtime()


def _log(message: str, *args: Any) -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    v229._log(message, *args)


def _face_area(face: dict[str, Any]) -> int:
    try:
        return max(1, int(face.get("w", 0))) * max(1, int(face.get("h", 0)))
    except Exception:
        return 0


def _select_person_a_face(runtime: Any, image: bytes) -> dict[str, Any]:
    """Choose PERSON A among the two dominant faces, then take the leftmost one.

    V233 asks Gemini to keep PERSON A on the left and PERSON B on the right. Selecting
    from the two largest detections prevents a small background face from becoming
    target index 0 merely because it is farther left in the frame.
    """
    detector = getattr(runtime, "_detect_faces_for_choice", None)
    if not callable(detector):
        raise RuntimeError("FaceSwap detector is unavailable in runtime")
    faces = list(detector(image) or [])
    if len(faces) < 2:
        raise RuntimeError(f"expected at least 2 faces in composition, detected {len(faces)}")
    principal = sorted(faces, key=_face_area, reverse=True)[:2]
    person_a = min(principal, key=lambda f: (int(f.get("cx", f.get("x", 0))), int(f.get("cy", f.get("y", 0)))))
    _log(
        "AI_SELFIE_V233_TARGET faces=%s selected_display=%s api_index=%s box=%sx%s@%s,%s",
        len(faces), person_a.get("display_index"), person_a.get("api_index"),
        person_a.get("w"), person_a.get("h"), person_a.get("x"), person_a.get("y"),
    )
    return dict(person_a)


def _select_source_photo(runtime: Any, photos: list[bytes]) -> tuple[bytes, int]:
    """Use the cleanest single-face original; prefer photo #3 when quality is tied."""
    detector = getattr(runtime, "_detect_faces_for_choice", None)
    if not callable(detector):
        return bytes(photos[-1]), 3

    candidates: list[tuple[int, int, bytes]] = []
    for idx, raw in enumerate(photos, 1):
        try:
            faces = list(detector(bytes(raw)) or [])
        except Exception:
            faces = []
        if len(faces) == 1:
            candidates.append((_face_area(faces[0]), idx, bytes(raw)))
    if candidates:
        # Highest face area wins; photo #3 wins an exact tie.
        _, idx, raw = max(candidates, key=lambda item: (item[0], item[1]))
        return raw, idx
    return bytes(photos[-1]), 3


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool) -> str:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    base_prompt = v229._stage1_prompt(name, scene, shot_label, has_scene_image)
    return (
        base_prompt
        + " COMPOSITION LOCK FOR IDENTITY TRANSFER: PERSON A (the user) must be the LEFT principal person in the final frame and PERSON B must be the RIGHT principal person. "
        + "Both principal faces must be clearly visible, unobstructed, at least medium-close, and large enough for deterministic face replacement. Do not put another face to the left of PERSON A."
    )


async def _true_face_transfer(runtime: Any, stage1: bytes, photos: list[bytes]) -> tuple[bytes, str, int]:
    target_face = _select_person_a_face(runtime, stage1)
    target_index = int(target_face.get("api_index", 0) or 0)
    source, source_photo_no = _select_source_photo(runtime, photos)

    segmind = getattr(runtime, "_segmind_faceswap_v2", None)
    piapi = getattr(runtime, "_piapi_faceswap", None)
    composite = getattr(runtime, "_faceswap_composite_selected_region", None)
    normalize = getattr(runtime, "_maybe_resize_output_image", None)

    errors: list[str] = []
    swapped: bytes | None = None
    provider = ""

    # Segmind v2 is first because it has deterministic indexed target selection.
    if callable(segmind) and bool(getattr(runtime, "SEGMIND_API_KEY", "")):
        try:
            _log("AI_SELFIE_V233_TRANSFER provider=segmind_v2 target_index=%s source_photo=%s", target_index, source_photo_no)
            candidate = await segmind(stage1, source, target_index=target_index, source_index=0)
            if candidate and len(candidate) > 1024:
                swapped = bytes(candidate)
                provider = "segmind_faceswap_v2"
        except Exception as exc:
            errors.append(f"segmind:{type(exc).__name__}:{exc}")

    # PiAPI fallback. The target index is still supplied; the final ROI composite
    # prevents accidental provider edits outside PERSON A even if the backend ignores it.
    if swapped is None and callable(piapi) and bool(getattr(runtime, "PIAPI_API_KEY", "")):
        try:
            _log("AI_SELFIE_V233_TRANSFER provider=piapi target_index=%s source_photo=%s", target_index, source_photo_no)
            candidate = await piapi(stage1, source, quality="fast", target_index=target_index, source_index=0)
            if candidate and len(candidate) > 1024:
                swapped = bytes(candidate)
                provider = "piapi_faceswap"
        except Exception as exc:
            errors.append(f"piapi:{type(exc).__name__}:{exc}")

    if swapped is None:
        raise RuntimeError("true face transfer failed: " + (" | ".join(errors) if errors else "no configured FaceSwap provider"))

    # Critical safety/quality step: restore the original Gemini frame everywhere
    # except a feathered region around PERSON A. This protects MrBeast and the scene.
    if callable(composite):
        try:
            swapped = bytes(composite(stage1, swapped, target_face))
        except Exception as exc:
            errors.append(f"composite:{type(exc).__name__}:{exc}")
    if callable(normalize):
        with contextlib.suppress(Exception):
            swapped = bytes(normalize(swapped))

    _log(
        "AI_SELFIE_V233_TRANSFER status=success provider=%s source_photo=%s target_index=%s bytes=%s",
        provider, source_photo_no, target_index, len(swapped),
    )
    return swapped, provider, source_photo_no


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229

    runtime = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    photos = v219._photos(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or context.user_data.get("cs215_scene_text") or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == v215.SCENE_IMAGE else None

    if not meta or len(photos) != 3 or shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON} or not v219._scene_ready(context):
        await delivery._safe_text(message, "❌ Не хватает данных: нужны 3 фото пользователя, герой, тип кадра и сцена.")
        return False
    if not v229._key():
        await delivery._safe_text(message, "❌ Отсутствует GEMINI_IMAGE_API_KEY.")
        return False
    if not (bool(getattr(runtime, "SEGMIND_API_KEY", "")) or bool(getattr(runtime, "PIAPI_API_KEY", ""))):
        await delivery._safe_text(message, "❌ Для точного переноса лица нужен SEGMIND_API_KEY или PIAPI_API_KEY.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    result = {"ok": False}
    user_refs, hero_refs = v229._identity_refs(photos, slug)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE: preserve exact location and composition", bytes(scene_image)))
    stage1_refs.extend(user_refs)
    stage1_refs.extend(hero_refs)

    async def action() -> bool:
        try:
            await delivery._safe_text(message, f"⏳ Этап 1/2: создаю сцену через рабочий Gemini V232. Референсов: {len(stage1_refs)}.")
            stage1, model1 = await v229._call_google(
                _stage1_prompt(str(meta['name']), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "composition",
            )
            await delivery._safe_text(message, "🧬 Этап 2/2: переношу ваше реальное лицо на PERSON A без перерисовки сцены.")
            final, provider, source_photo_no = await _true_face_transfer(runtime, stage1, photos)

            caption = (
                f"🎭 AI-селфи с персонажем «{meta['name']}» готово ✅\n"
                f"Сцена: Gemini {model1}. Лицо пользователя: настоящий FaceSwap ({provider}), источник — фото №{source_photo_no}.\n"
                "Герой и остальная сцена защищены локальным композитингом. "
                "Изображение создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Три фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V233 true face-transfer selfie failed", exc)
            await delivery._safe_text(message, f"❌ Не удалось безопасно перенести лицо. Черновая сцена не отправлена. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v233_true_face_transfer",
        "remember_payload": {
            "character": slug,
            "scene_provider": "google_gemini_direct",
            "identity_provider": "segmind_v2_then_piapi",
            "stages": 2,
            "user_originals": 3,
            "hero_refs": 3,
            "scene_image": has_scene_image,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


def install() -> None:
    """Replace only the V229 generate symbol; its proven UI/owner machinery stays intact."""
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    v229.generate = generate
    v229.VERSION = VERSION
    _log("[neyrobot-prod] V233 true face-transfer overlay installed on V232/V229 owner")


__all__ = ["VERSION", "generate", "install"]
