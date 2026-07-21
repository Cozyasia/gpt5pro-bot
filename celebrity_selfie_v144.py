# -*- coding: utf-8 -*-
"""Celebrity Selfie v144: provider-safe scene plates and strict retries.

v143 correctly fails closed on bad composites.  The next production failure was
upstream: an empty/``auto`` aspect ratio reached Gemini's responseFormat image
configuration and OpenAI sometimes returned a plate without a detectable main
person.  v144 fixes the scene stage without weakening v143's final gates:

* every requested aspect ratio is normalized to a model-supported value;
* Gemini retries three compatible REST request shapes, ending with no explicit
  aspect configuration instead of failing the whole provider route;
* scene presets are rewritten as private, single-subject compositions with one
  close companion on the right and clean space on the left;
* OpenAI and Gemini receive multiple controlled attempts plus a stricter rescue
  pass when the first plate set contains no usable candidate;
* a local zero-face result may only survive when independent Vision QC confirms
  exactly one visible right-side foreground person; extra people remain blocked;
* diagnostics report the normalized aspect, schema fallbacks and every attempt.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import os
import time
from typing import Any, Awaitable, Callable

import httpx

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143

VERSION = "v144-scene-provider-schema-retry-2026-07-21"
_GROUP = -2_100_000_700
_BUILDER_FLAG = "_celebrity_selfie_v144_builder"
_HANDLER_FLAG = "_celebrity_selfie_v144_handlers"

_ORIGINAL_V143_RUN = v143._run_v143_generation
_ORIGINAL_V143_PLATE_PROBLEM = v143._plate_problem
_LAST_RUN_DEBUG: dict[str, Any] = {}
_VISION_APPROVED_PLATES: set[str] = set()

_ALLOWED_ASPECTS = {
    "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9",
}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _normalise_aspect(value: Any) -> str:
    raw = str(value or "").strip().casefold().replace("×", ":").replace("x", ":")
    aliases = {
        "": "4:5", "-": "4:5", "auto": "4:5", "portrait": "4:5", "vertical": "4:5",
        "landscape": "3:2", "horizontal": "3:2", "square": "1:1", "story": "9:16",
        "4/5": "4:5", "3/4": "3:4", "2/3": "2:3", "3/2": "3:2", "16/9": "16:9",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in _ALLOWED_ASPECTS else "4:5"


def _scene_profile(scene: str) -> str:
    text = str(scene or "").strip()
    lowered = text.casefold()
    if "ресторан" in lowered or "restaurant" in lowered:
        return (
            "a private premium restaurant booth with warm practical lighting, an elegant table and quiet cinematic background; "
            "there are no other guests, waiters, mirrors with faces or portraits"
        )
    if "яхт" in lowered or "yacht" in lowered or "boat" in lowered:
        return (
            "the private aft deck of a luxury yacht at a marina, with water and yacht details behind; no crew, passengers, "
            "reflections with people or other foreground figures"
        )
    if "премьер" in lowered or "premiere" in lowered or "red carpet" in lowered:
        return (
            "a private red-carpet photo-call alcove with cinema lights and velvet ropes after hours; no crowd, photographers, "
            "posters with faces or additional guests"
        )
    if "выстав" in lowered or "gallery" in lowered or "exhibition" in lowered:
        return (
            "a quiet contemporary gallery corner with tasteful exhibits and soft museum lighting; no visitors, portraits, "
            "reflections or background faces"
        )
    if "красн" in lowered or "red square" in lowered or "kremlin" in lowered:
        return (
            "a quiet early-morning premium viewpoint near Red Square with recognizable Kremlin and St Basil architectural context; "
            "the public area is empty, with no guards, ceremony, crowd, posters or extra people"
        )
    return (
        f"a private, uncrowded interpretation of this requested setting: {text or 'an elegant premium location'}; "
        "remove every secondary person, portrait, reflection and screen face"
    )


def _scene_prompt(scene: str, aspect: str, variant: int, lighting: str, *, rescue: bool = False) -> str:
    safe_aspect = _normalise_aspect(aspect)
    framings = (
        "close chest-up smartphone selfie plate",
        "natural waist-up smartphone selfie plate",
        "premium shoulder-level mobile photograph",
        "close editorial phone-camera portrait",
    )
    strength = (
        "This is a corrective retry. Obey the person count and placement literally. "
        if rescue else
        "Obey the person count and placement literally. "
    )
    return (
        "Create one seamless photorealistic smartphone photograph for later compositing. "
        + strength
        + "Show EXACTLY ONE adult man in the entire image. He is the only visible human and the only face. Place him on the RIGHT, "
        "chest-up or waist-up, close enough that his unobstructed face is clearly detectable, looking naturally toward the phone "
        "camera, with shoulders angled slightly toward the empty left side. Keep the LEFT 42 percent completely free for inserting "
        "another real person later: no body, hand, face, reflection, portrait, poster, sculpture face, phone-screen face or dark human "
        "silhouette there. No crowd anywhere, no distant people, no staff, no guards and no second prominent subject. "
        f"Setting: {_scene_profile(scene)}. Framing: {framings[variant % len(framings)]}. "
        f"Lighting: {lighting}; one coherent light direction, realistic mobile HDR, natural skin texture and correct anatomy. "
        "The right-side man's face should occupy roughly 3 to 10 percent of the image area and sit in the upper-middle region. "
        "No collage, split screen, inset, contact sheet, text, logo, watermark or border. "
        f"Output aspect ratio {safe_aspect}. Return only the final image."
    )


def _gemini_payload_variants(provider: Any, prompt: str, aspect: str, image_size: str) -> list[tuple[str, dict[str, Any]]]:
    safe_aspect = _normalise_aspect(aspect)
    size = str(image_size or "2K").upper()
    if size not in {"512", "1K", "2K", "4K"}:
        size = "2K"
    base = provider._gemini_payload(prompt, [], aspect=safe_aspect, image_size=size)

    full = copy.deepcopy(base)
    config = full.setdefault("generationConfig", {})
    config["responseModalities"] = ["IMAGE"]
    config["responseFormat"] = {"image": {"aspectRatio": safe_aspect, "imageSize": size}}

    aspect_only = copy.deepcopy(full)
    aspect_only["generationConfig"]["responseFormat"] = {"image": {"aspectRatio": safe_aspect}}

    modalities_only = copy.deepcopy(full)
    modalities_only["generationConfig"].pop("responseFormat", None)
    modalities_only["generationConfig"]["responseModalities"] = ["IMAGE"]
    return [
        ("response-format-aspect-size", full),
        ("response-format-aspect", aspect_only),
        ("response-modalities-only", modalities_only),
    ]


async def _gemini_scene_direct(mod: Any, model: str, prompt: str, aspect: str, debug: dict[str, Any] | None = None) -> bytes:
    provider = v139.selfie.previous
    key = provider._gemini_key(mod)
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY missing")
    base_url = str(
        getattr(mod, "GEMINI_IMAGE_BASE_URL", "")
        or os.environ.get("GEMINI_IMAGE_BASE_URL")
        or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    image_size = str(os.environ.get("CELEBRITY_GEMINI_IMAGE_SIZE") or "2K").upper()
    timeout_s = _integer("CELEBRITY_V144_GEMINI_TIMEOUT_S", 420, 90, 900)
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180),
        follow_redirects=True,
    ) as client:
        for schema, payload in _gemini_payload_variants(provider, prompt, aspect, image_size):
            if debug is not None:
                debug.setdefault("gemini_schema_attempts", []).append({
                    "model": model,
                    "schema": schema,
                    "aspect": _normalise_aspect(aspect),
                })
            try:
                response = await client.post(
                    f"{base_url}/models/{model}:generateContent",
                    headers={"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
                    json=payload,
                )
                try:
                    data = response.json()
                except Exception as exc:
                    errors.append(f"{schema}: invalid JSON HTTP {response.status_code}: {response.text[:280]}")
                    continue
                if response.status_code >= 400:
                    detail = provider._gemini_error(data) or response.text[:450]
                    errors.append(f"{schema}: HTTP {response.status_code}: {detail}")
                    continue
                images = provider._gemini_images(data)
                if not images:
                    errors.append(f"{schema}: returned no image")
                    continue
                for raw in reversed(images):
                    try:
                        return v139._jpeg(raw)
                    except Exception as exc:
                        errors.append(f"{schema}: unreadable image: {v139._safe_error(exc)}")
            except Exception as exc:
                errors.append(f"{schema}: {v139._safe_error(exc)}")
    raise RuntimeError(f"Gemini scene {model} failed all compatible schemas: " + " | ".join(errors[-6:])[:1600])


def _plate_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plate_problem(raw: bytes, label: str) -> str:
    problem = _ORIGINAL_V143_PLATE_PROBLEM(raw, label)
    if not problem:
        return ""
    lowered = str(problem).casefold()
    if "found 0" in lowered:
        digest = _plate_digest(raw)
        if digest in _VISION_APPROVED_PLATES:
            return ""
        # After identity insertion v143 immediately performs strict Vision identity
        # QC, so allow only an already structurally generated celebrity stage to
        # reach that independent check. Initial scene plates still need approval.
        if "celebrity" in str(label).casefold() or "identity" in str(label).casefold():
            return ""
    return problem


async def _vision_plate_qc(mod: Any, raw: bytes) -> dict[str, Any]:
    vision = getattr(mod, "ask_openai_vision", None)
    if not callable(vision) or not _flag("CELEBRITY_V144_VISION_ZERO_FACE_RESCUE", True):
        return {"accepted": False, "reason": "vision plate QC unavailable"}
    prompt = (
        "Strict scene-plate QC. Do not identify or name anyone. Inspect this single generated image. Return JSON only with: "
        "exactly_one_main_foreground_adult boolean, main_face_clearly_visible boolean, main_person_on_right boolean, "
        "left_side_clear_for_composite boolean, no_extra_prominent_people boolean, no_portrait_or_reflection_faces boolean, "
        "naturalness integer 0-100, reason short string. Accept tiny unrecognizable background shapes only when they are clearly "
        "not people or faces."
    )
    try:
        answer = await vision(prompt, base64.b64encode(v139._jpeg(raw, max_side=1800, quality=94)).decode("ascii"), "image/jpeg")
        data = v139._json_object(answer) or {}
        accepted = (
            data.get("exactly_one_main_foreground_adult") is True
            and data.get("main_face_clearly_visible") is True
            and data.get("main_person_on_right") is True
            and data.get("left_side_clear_for_composite") is True
            and data.get("no_extra_prominent_people") is True
            and data.get("no_portrait_or_reflection_faces") is True
            and float(data.get("naturalness") or 0) >= 62
        )
        return {
            "accepted": bool(accepted),
            "naturalness": float(data.get("naturalness") or 0),
            "reason": str(data.get("reason") or "")[:350],
            "checks": data,
        }
    except Exception as exc:
        return {"accepted": False, "reason": f"vision-plate-qc-error:{v139._safe_error(exc)}"[:350]}


async def _make_plate_candidates(mod: Any, scene: str, aspect: str, user_photo: bytes, debug: dict[str, Any]) -> list[dict[str, Any]]:
    safe_aspect = _normalise_aspect(aspect)
    lighting = v142._lighting_hint(user_photo)
    candidates: list[dict[str, Any]] = []
    debug["scene_aspect_requested"] = str(aspect or "-")
    debug["scene_aspect_normalized"] = safe_aspect
    debug["scene_prompt_profile"] = _scene_profile(scene)
    debug.setdefault("gemini_schema_attempts", [])
    debug.setdefault("plate_attempts", [])

    jobs: list[tuple[str, str, Callable[[], Awaitable[bytes]]]] = []
    gemini_key = v139.selfie.previous._gemini_key(mod)
    openai_key = v139.selfie._openai_key(mod)

    if gemini_key and _flag("CELEBRITY_V144_GEMINI_SCENE_ENABLED", True):
        models = v139.selfie.previous._gemini_models(mod) or ["gemini-3-pro-image", "gemini-3.1-flash-image"]
        count = _integer("CELEBRITY_V144_GEMINI_PLATES", 2, 0, 4)
        for index in range(count):
            model = models[index % len(models)]
            prompt = _scene_prompt(scene, safe_aspect, index, lighting)
            jobs.append((
                f"v144_plate_gemini_{index + 1}",
                f"gemini:{model}",
                lambda model=model, prompt=prompt: _gemini_scene_direct(mod, model, prompt, safe_aspect, debug),
            ))

    if openai_key and _flag("CELEBRITY_V144_OPENAI_SCENE_ENABLED", True):
        count = _integer("CELEBRITY_V144_OPENAI_PLATES", 2, 0, 4)
        for index in range(count):
            prompt = _scene_prompt(scene, safe_aspect, index + 2, lighting)
            jobs.append((
                f"v144_plate_openai_{index + 1}",
                "openai:official-images",
                lambda prompt=prompt: v140._openai_scene_direct(mod, prompt, safe_aspect),
            ))

    if v139.selfie._bfl_key() and _flag("CELEBRITY_V144_FLUX_SCENE_ENABLED", True):
        prompt = _scene_prompt(scene, safe_aspect, 1, lighting)
        jobs.append((
            "v144_plate_flux_1",
            f"bfl:{os.environ.get('CELEBRITY_FLUX_MODEL') or 'flux-2-pro'}",
            lambda prompt=prompt: v139.selfie._flux_edit(prompt, [], safe_aspect),
        ))

    semaphore = asyncio.Semaphore(_integer("CELEBRITY_V144_SCENE_PARALLEL", 2, 1, 3))

    async def run_job(name: str, provider: str, factory: Callable[[], Awaitable[bytes]], *, rescue: bool = False) -> None:
        async with semaphore:
            stage = v139._stage_start(debug, name, provider, rescue=rescue, aspect=safe_aspect)
            attempt = {"stage": name, "provider": provider, "rescue": rescue, "aspect": safe_aspect}
            debug["plate_attempts"].append(attempt)
            try:
                raw = await factory()
                problem = _ORIGINAL_V143_PLATE_PROBLEM(raw, name)
                vision_qc: dict[str, Any] | None = None
                if problem and "found 0" in str(problem).casefold():
                    vision_qc = await _vision_plate_qc(mod, raw)
                    attempt["zero_face_vision_qc"] = vision_qc
                    if vision_qc.get("accepted"):
                        _VISION_APPROVED_PLATES.add(_plate_digest(raw))
                        problem = ""
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                score = v142._plate_score(raw)
                if vision_qc and vision_qc.get("accepted"):
                    score += min(18.0, float(vision_qc.get("naturalness") or 0) * 0.12)
                row = {
                    "label": name,
                    "provider": provider,
                    "score": round(score, 2),
                    "output": raw,
                    "aspect": safe_aspect,
                    "vision_plate_approved": bool(vision_qc and vision_qc.get("accepted")),
                }
                candidates.append(row)
                debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
                attempt["status"] = "ok"
                attempt["score"] = row["score"]
                v139._stage_finish(stage, "ok", score=row["score"], bytes=len(raw), vision_rescue=row["vision_plate_approved"])
            except Exception as exc:
                attempt["status"] = "error"
                attempt["error"] = v139._safe_error(exc)[:600]
                v139._record_error(debug, stage, exc)

    if jobs:
        await asyncio.gather(*(run_job(*job) for job in jobs))

    # If every normal candidate failed, perform a deliberately close, low-clutter
    # rescue round. This addresses OpenAI outputs where the sole person is too
    # small for local face detection, without relaxing the final v143 gates.
    if not candidates and _flag("CELEBRITY_V144_STRICT_RESCUE_ROUND", True):
        rescue_jobs: list[tuple[str, str, Callable[[], Awaitable[bytes]]]] = []
        rescue_prompt = _scene_prompt(scene, safe_aspect, 3, lighting, rescue=True)
        if openai_key:
            rescue_jobs.append((
                "v144_plate_openai_rescue",
                "openai:official-images-rescue",
                lambda: v140._openai_scene_direct(mod, rescue_prompt, safe_aspect),
            ))
        if gemini_key:
            models = v139.selfie.previous._gemini_models(mod) or ["gemini-3.1-flash-image"]
            model = models[-1]
            rescue_jobs.append((
                "v144_plate_gemini_rescue",
                f"gemini:{model}:schema-fallback",
                lambda model=model: _gemini_scene_direct(mod, model, rescue_prompt, safe_aspect, debug),
            ))
        for rescue_job in rescue_jobs:
            await run_job(*rescue_job, rescue=True)
            if candidates:
                break

    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


async def _run_v144_generation(
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
    started = time.time()
    try:
        output, debug = await _ORIGINAL_V143_RUN(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            previous_result=previous_result,
            additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update({
            "version": VERSION,
            "scene_provider_contract": "normalized-aspect+gemini-schema-fallback+multi-attempt+strict-rescue",
            "scene_aspect_normalized": debug.get("scene_aspect_normalized") or "4:5",
            "v144_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        v143._LAST_RUN_DEBUG = debug
        v142._LAST_RUN_DEBUG = debug
        v139._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update({
            "version": VERSION,
            "scene_provider_contract": "normalized-aspect+gemini-schema-fallback+multi-attempt+strict-rescue",
            "v144_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        v143._LAST_RUN_DEBUG = debug
        v142._LAST_RUN_DEBUG = debug
        v139._LAST_RUN_DEBUG = debug
        if isinstance(exc, v139.PipelineError):
            exc.debug = debug
        raise


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
    output, _ = await _run_v144_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or _LAST_RUN_DEBUG or v143._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=strict_preserve_user+provider_safe_scene_plates",
        "gemini_payload=normalized_responseFormat_with_modalities_only_fallback",
        "openai_scene=multi_attempt+strict_rescue",
        "scene_plate_gate=one_main_person_right+left_space_clear",
        "zero_face_local_detector=vision_confirmation_required",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"aspect_requested={debug.get('scene_aspect_requested') or '-'}",
        f"aspect_normalized={debug.get('scene_aspect_normalized') or '4:5'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"gemini_schema_attempts={str(debug.get('gemini_schema_attempts') or '-')[:1400]}",
        f"plate_attempts={str(debug.get('plate_attempts') or '-')[:1800]}",
        f"delivery_mode={session.get('delivery_mode') or '-'}",
        f"selected={str(selected or '-')[:1800]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    errors = debug.get("errors") or []
    if errors:
        lines.append("errors:")
        for item in errors[-10:]:
            lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:360]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    os.environ.setdefault("CELEBRITY_V144_GEMINI_SCENE_ENABLED", "1")
    os.environ.setdefault("CELEBRITY_V144_OPENAI_SCENE_ENABLED", "1")
    os.environ.setdefault("CELEBRITY_V144_GEMINI_PLATES", "2")
    os.environ.setdefault("CELEBRITY_V144_OPENAI_PLATES", "2")
    os.environ.setdefault("CELEBRITY_V144_SCENE_PARALLEL", "2")
    os.environ.setdefault("CELEBRITY_V144_STRICT_RESCUE_ROUND", "1")
    os.environ.setdefault("CELEBRITY_V144_VISION_ZERO_FACE_RESCUE", "1")
    os.environ.setdefault("CELEBRITY_V144_GEMINI_TIMEOUT_S", "420")
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"

    v142._make_plate_candidates = _make_plate_candidates
    v143._plate_problem = _plate_problem
    v139.selfie._run_v144_generation = _run_v144_generation
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._diag = _diag


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
        # Re-apply after every legacy builder hook has completed.
        install()
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v144",
                "diag_selfie_v143",
                "diag_selfie_v142",
                "diag_selfie_v141",
                "diag_selfie_v139",
                "diag_celebrity_flow",
                "diag_brand",
            ):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


__all__ = [
    "VERSION",
    "install",
    "install_builder_hook",
    "_normalise_aspect",
    "_scene_profile",
    "_scene_prompt",
    "_gemini_payload_variants",
    "_gemini_scene_direct",
    "_plate_problem",
    "_vision_plate_qc",
    "_make_plate_candidates",
    "_run_v144_generation",
    "_diag",
]
