# -*- coding: utf-8 -*-
"""V235: stable Gemini scene + isolated real FaceSwap for PERSON A only.

The key rule is separation of identities:
- Gemini gets ONE user source photo only for pose/expression/body guidance.
- PERSON B gets ONLY the three hero references and must never inherit user traits.
- FaceSwap runs on an isolated left-side crop containing PERSON A, not on the full
  two-person composition. This removes provider face-index ambiguity and guarantees
  that the hero/right side is never modified by the FaceSwap provider.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
from typing import Any

VERSION = "v235-isolated-person-a-faceswap-hero-protect-2026-08-18"
_HANDLER_FLAG = "_neyrobot_v234_real_faceswap_handler"
_STARTED = False
_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)"


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    return v229._runtime()


def _log(message: str, *args: Any) -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    v229._log(message, *args)


def _detect(runtime: Any, image: bytes) -> list[dict[str, Any]]:
    """Best-effort only. Detection failure must never choose a different person."""
    detector = getattr(runtime, "_detect_faces_for_choice", None)
    if not callable(detector):
        return []
    try:
        return [dict(x) for x in (detector(bytes(image)) or [])]
    except Exception:
        return []


def _face_area(face: dict[str, Any]) -> int:
    try:
        return max(1, int(face.get("w", 0))) * max(1, int(face.get("h", 0)))
    except Exception:
        return 0


def _select_source_photo(runtime: Any, photos: list[bytes]) -> tuple[bytes, int, dict[str, Any] | None]:
    """Use strongest single-face original when detectable; otherwise keep photo #3."""
    candidates: list[tuple[int, int, bytes, dict[str, Any]]] = []
    for idx, raw in enumerate(photos, 1):
        faces = _detect(runtime, bytes(raw))
        if len(faces) == 1:
            candidates.append((_face_area(faces[0]), idx, bytes(raw), faces[0]))
    if candidates:
        _, idx, raw, face = max(candidates, key=lambda item: (item[0], item[1]))
        return raw, idx, face
    raw = bytes(photos[-1])
    return raw, 3, None


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    scene_rule = (
        "The first reference is the AUTHORITATIVE SCENE BASE. Preserve its architecture, furniture, camera viewpoint, perspective and lighting. "
        if has_scene_image else
        f"Create this location faithfully: {scene}. "
    )
    return (
        "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
        f"SHOT MODE: {shot_label}. {scene_rule}"
        f"PERSON A is the USER and must be on the LEFT. The reference labelled USER SOURCE PHOTO #{source_photo_no} belongs ONLY to PERSON A. "
        "Use that user reference ONLY to copy PERSON A's body build, hair, head angle, facial expression, mouth openness, eye direction and natural pose. "
        "PERSON A's generated facial identity is temporary and will be physically replaced later; therefore do not spend identity capacity inventing or beautifying PERSON A. "
        "Make PERSON A near-frontal, upright, unobstructed, sharp and sufficiently large for a direct face transfer. Keep PERSON A clearly inside the LEFT 48 percent of the image. "
        f"PERSON B is {name} and must be on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
        "ABSOLUTE IDENTITY SEPARATION: never copy any USER facial feature, hair feature, age, jaw, eyes, nose, mouth, skin or expression into PERSON B. "
        "Likewise never copy PERSON B identity into PERSON A. PERSON B must remain unmistakably the hero defined by the HERO PORTRAIT references. "
        "Keep the two heads separated horizontally with visible space between them. PERSON B must stay entirely in the RIGHT 48 percent of the image. "
        "Natural anatomy, realistic skin and optics. No text, watermark, duplicated face, merged identity, morphing or hybrid face."
    )


def _left_person_crop(image: bytes) -> tuple[bytes, tuple[int, int, int, int]]:
    """Crop only PERSON A's reserved left-side region; hero is excluded by construction."""
    from PIL import Image
    im = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = im.size
    # V235 prompt reserves the left half for PERSON A. Keep a little margin but never
    # reach the right-side hero. Vertical crop includes head/neck/upper torso.
    x0 = 0
    y0 = 0
    x1 = max(256, min(w, int(w * 0.52)))
    y1 = max(256, min(h, int(h * 0.78)))
    crop = im.crop((x0, y0, x1, y1))
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=96, subsampling=0)
    return out.getvalue(), (x0, y0, x1, y1)


def _merge_left_crop(base: bytes, swapped_crop: bytes, box: tuple[int, int, int, int]) -> bytes:
    """Blend provider output back only into PERSON A region; right-side hero is pixel-locked."""
    from PIL import Image, ImageFilter
    base_im = Image.open(io.BytesIO(base)).convert("RGB")
    crop_im = Image.open(io.BytesIO(swapped_crop)).convert("RGB")
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    if crop_im.size != (cw, ch):
        crop_im = crop_im.resize((cw, ch), Image.Resampling.LANCZOS)

    # Rectangular feather mask: provider may alter pixels inside user crop, but nothing
    # outside it. The soft edge prevents a visible seam at the crop boundary.
    mask = Image.new("L", (cw, ch), 255)
    feather = max(12, min(48, int(min(cw, ch) * 0.04)))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    base_im.paste(crop_im, (x0, y0), mask)

    out = io.BytesIO()
    base_im.save(out, format="JPEG", quality=96, subsampling=0)
    return out.getvalue()


async def _true_face_transfer(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int) -> tuple[bytes, str]:
    """Swap a single isolated PERSON A crop, then merge it into untouched stage1."""
    segmind = getattr(runtime, "_segmind_faceswap_v2", None)
    piapi = getattr(runtime, "_piapi_faceswap", None)
    normalize = getattr(runtime, "_maybe_resize_output_image", None)

    target_crop, box = _left_person_crop(stage1)
    target_sha = hashlib.sha256(target_crop).hexdigest()[:12]
    errors: list[str] = []
    swapped_crop: bytes | None = None
    provider = ""

    _log(
        "AI_SELFIE_V235_CROP box=%s,%s,%s,%s target_sha=%s bytes=%s mode=isolated_person_a",
        box[0], box[1], box[2], box[3], target_sha, len(target_crop),
    )

    # Single-face crop means target_index=0 is unambiguous. The hero is not present in
    # this provider request at all, so FaceSwap cannot modify or acquire hero identity.
    if callable(segmind) and bool(getattr(runtime, "SEGMIND_API_KEY", "")):
        try:
            _log("AI_SELFIE_V235_TRANSFER provider=segmind_v2 isolated=true target_index=0 source_photo=%s", source_photo_no)
            candidate = await segmind(target_crop, source, target_index=0, source_index=0)
            if candidate and len(candidate) > 1024 and hashlib.sha256(bytes(candidate)).hexdigest()[:12] != target_sha:
                swapped_crop = bytes(candidate)
                provider = "segmind_faceswap_v2_isolated"
            else:
                errors.append("segmind:no_effect_or_empty")
        except Exception as exc:
            errors.append(f"segmind:{type(exc).__name__}:{exc}")

    if swapped_crop is None and callable(piapi) and bool(getattr(runtime, "PIAPI_API_KEY", "")):
        try:
            _log("AI_SELFIE_V235_TRANSFER provider=piapi isolated=true target_index=0 source_photo=%s", source_photo_no)
            candidate = await piapi(target_crop, source, quality="fast", target_index=0, source_index=0)
            if candidate and len(candidate) > 1024 and hashlib.sha256(bytes(candidate)).hexdigest()[:12] != target_sha:
                swapped_crop = bytes(candidate)
                provider = "piapi_faceswap_isolated"
            else:
                errors.append("piapi:no_effect_or_empty")
        except Exception as exc:
            errors.append(f"piapi:{type(exc).__name__}:{exc}")

    if swapped_crop is None:
        raise RuntimeError("isolated real FaceSwap produced no usable transfer: " + (" | ".join(errors) if errors else "no provider configured"))

    final = _merge_left_crop(stage1, swapped_crop, box)
    if callable(normalize):
        with contextlib.suppress(Exception):
            final = bytes(normalize(final))

    _log(
        "AI_SELFIE_V235_TRANSFER status=success provider=%s source_photo=%s isolated=true base_sha=%s final_sha=%s bytes=%s hero_region=untouched",
        provider, source_photo_no, hashlib.sha256(stage1).hexdigest()[:12], hashlib.sha256(final).hexdigest()[:12], len(final),
    )
    return final, provider


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
        await delivery._safe_text(message, "❌ Для реального переноса лица нужен SEGMIND_API_KEY или PIAPI_API_KEY.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    source, source_photo_no, _ = _select_source_photo(runtime, photos)
    result = {"ok": False}

    # Critical V235 change: do NOT feed Gemini six user identity references. That was
    # contaminating PERSON B. Gemini receives exactly one user source + three hero refs.
    _, hero_refs = v229._identity_refs(photos, slug)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE — location only; contains no identity authority", bytes(scene_image)))
    stage1_refs.append((f"USER SOURCE PHOTO #{source_photo_no} — PERSON A ONLY: pose/expression/body; NEVER apply to PERSON B", source))
    stage1_refs.extend(hero_refs)

    async def action() -> bool:
        try:
            await delivery._safe_text(message, f"⏳ Этап 1/2: создаю сцену. Пользователь слева, герой справа; личности разделены. Источник лица — фото №{source_photo_no}.")
            stage1, model1 = await v229._call_google(
                _stage1_prompt(str(meta['name']), scene_text, v215._shot_label(shot_mode), has_scene_image, source_photo_no),
                stage1_refs,
                "composition_identity_separated",
            )
            await delivery._safe_text(message, "🧬 Этап 2/2: изолирую левую область пользователя и переношу туда реальное лицо. Область героя в FaceSwap не отправляется.")
            final, provider = await _true_face_transfer(runtime, stage1, source, source_photo_no)

            caption = (
                f"🎭 AI-селфи с персонажем «{meta['name']}» готово ✅\n"
                f"Сцена: Gemini {model1}. Лицо пользователя: изолированный реальный FaceSwap ({provider}), источник — фото №{source_photo_no}.\n"
                "Личность героя защищена отдельными референсами и не передаётся в FaceSwap. "
                "Изображение создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Три фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V235 isolated real face-transfer selfie failed", exc)
            await delivery._safe_text(message, f"❌ Реальный перенос лица не выполнен; синтетическое лицо не отправляю. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v235_isolated_faceswap",
        "remember_payload": {
            "character": slug,
            "scene_provider": "google_gemini_direct",
            "identity_provider": "segmind_then_piapi_isolated_person_a",
            "stages": 2,
            "source_photo": source_photo_no,
            "hero_region_protected": True,
            "gemini_user_refs": 1,
            "hero_refs": 3,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


async def generation_callback(update: Any, context: Any) -> None:
    """Hard owner for the three generation buttons; blocks all legacy owners."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")
    with contextlib.suppress(Exception):
        await query.answer()

    if data.startswith("cs201:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if preset:
            context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
            context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
            context.user_data.pop("cs215_scene_image", None)
            await generate(update, context, context.user_data["cs215_scene_text"])
        else:
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(_runtime()))
        raise ApplicationHandlerStop

    if data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if v219._scene_ready(context):
            await generate(update, context, str(context.user_data.get("cs215_scene_text") or ""))
        else:
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(_runtime()))
        raise ApplicationHandlerStop


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)):
        return False
    if getattr(app, _HANDLER_FLAG, False):
        return True
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(generation_callback, pattern=_GENERATION_PATTERN), group=-1000000)
    setattr(app, _HANDLER_FLAG, True)
    _log("AI_SELFIE_V235_BIND status=ok group=-1000000")
    return True


def _bind_runtime_apps() -> None:
    runtime = _runtime()
    if runtime is None:
        return
    for value in list(vars(runtime).values()):
        with contextlib.suppress(Exception):
            bind_application(value)


def install() -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    v229.generate = generate
    v229.VERSION = VERSION
    v219.generate = generate
    with contextlib.suppress(Exception):
        v219.public_callback.__globals__["generate"] = generate
    _bind_runtime_apps()
    if not getattr(install, "_logged", False):
        _log("[neyrobot-prod] V235 isolated PERSON-A FaceSwap installed version=%s", VERSION)
        setattr(install, "_logged", True)


def install_async() -> None:
    global _STARTED
    install()
    _STARTED = True


__all__ = ["VERSION", "generate", "generation_callback", "bind_application", "install", "install_async"]
