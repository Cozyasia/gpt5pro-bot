# -*- coding: utf-8 -*-
"""Celebrity Selfie v140: provider-compatible scene generation and rescue.

v139's scene-first architecture is retained. This overlay hardens only the
scene stage and failure reporting:

* direct Gemini scene generation no longer depends on a changing internal
  function signature;
* OpenAI scene generation always uses the canonical Images endpoint and retries
  compatible request shapes;
* a one-shot OpenAI candidate may be promoted to a rescue scene and then passed
  through the normal left/right identity locks;
* a conservative one-shot final fallback remains available when every scene
  route fails;
* failure cards include the real provider/stage categories immediately.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Any, Awaitable, Callable

import httpx

import celebrity_selfie_v139 as v139

VERSION = "v140-scene-provider-rescue-2026-07-20"

_ORIGINAL_FAILURE_MESSAGE = v139._failure_message


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _soft_scene_problem(raw: bytes, stage: str) -> str:
    """Keep hard corruption/composite gates, but do not trust one-face false negatives."""
    problem = v139._structural_problem(raw, stage)
    text = str(problem or "").casefold()
    soft_markers = (
        "только одно уверенное лицо",
        "only one confident face",
        "found only one",
    )
    if problem and _flag("CELEBRITY_V140_SOFT_ONE_FACE_SCENE_GATE", True) and any(marker in text for marker in soft_markers):
        return ""
    return problem


async def _gemini_scene_direct(mod: Any, model: str, prompt: str, aspect: str) -> bytes:
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
    if image_size not in {"512", "1K", "2K", "4K"}:
        image_size = "2K"
    timeout_s = _integer("CELEBRITY_V140_GEMINI_TIMEOUT_S", 420, 90, 900)
    payload = provider._gemini_payload(prompt, [], aspect=aspect, image_size=image_size)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=180),
        follow_redirects=True,
    ) as client:
        response = await client.post(
            f"{base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
            json=payload,
        )
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"Gemini scene invalid JSON HTTP {response.status_code}: {response.text[:350]}") from exc
    if response.status_code >= 400:
        detail = provider._gemini_error(data) or response.text[:450]
        raise RuntimeError(f"Gemini scene {model} HTTP {response.status_code}: {detail}")
    images = provider._gemini_images(data)
    if not images:
        raise RuntimeError(f"Gemini scene {model} returned no image")
    errors: list[str] = []
    for raw in reversed(images):
        try:
            return v139._jpeg(raw)
        except Exception as exc:
            errors.append(v139._safe_error(exc))
    raise RuntimeError("Gemini scene images were unreadable: " + " | ".join(errors[-3:]))


def _openai_scene_base_url() -> str:
    configured = str(os.environ.get("CELEBRITY_V140_OPENAI_SCENE_BASE_URL") or os.environ.get("OPENAI_IMAGE_BASE_URL") or "").strip()
    if configured and "cometapi" not in configured.casefold():
        return configured.rstrip("/")
    return "https://api.openai.com/v1"


async def _openai_scene_direct(mod: Any, prompt: str, aspect: str) -> bytes:
    key = v139.selfie._openai_key(mod)
    if not key:
        raise RuntimeError("OpenAI image key missing")
    model = str(os.environ.get("CELEBRITY_OPENAI_IMAGE_MODEL") or getattr(mod, "IMAGES_MODEL", "") or "gpt-image-1").strip()
    if not model or "gemini" in model.casefold() or "comet" in model.casefold():
        model = "gpt-image-1"
    requested_size = v139.selfie._openai_size(aspect)
    sizes: list[str] = []
    for size in (requested_size, "1024x1024"):
        if size and size not in sizes:
            sizes.append(size)
    timeout_s = _integer("CELEBRITY_V140_OPENAI_TIMEOUT_S", 420, 90, 900)
    errors: list[str] = []
    variants: list[dict[str, Any]] = []
    for size in sizes:
        variants.extend([
            {"model": model, "prompt": prompt, "size": size, "quality": "high", "output_format": "jpeg", "n": 1},
            {"model": model, "prompt": prompt, "size": size, "quality": "medium", "n": 1},
        ])
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=40, read=timeout_s, write=240),
        follow_redirects=True,
    ) as client:
        for body in variants:
            try:
                response = await client.post(
                    _openai_scene_base_url() + "/images/generations",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
                    json=body,
                )
                if response.status_code >= 400:
                    errors.append(f"HTTP {response.status_code} size={body.get('size')} quality={body.get('quality')}: {response.text[:280]}")
                    continue
                payload = response.json()
                rows = payload.get("data") if isinstance(payload, dict) else None
                row = rows[0] if isinstance(rows, list) and rows else {}
                raw: bytes | None = None
                if isinstance(row, dict) and isinstance(row.get("b64_json"), str):
                    raw = base64.b64decode(row["b64_json"])
                elif isinstance(row, dict) and isinstance(row.get("url"), str):
                    image_response = await client.get(row["url"])
                    image_response.raise_for_status()
                    raw = image_response.content
                if raw:
                    return v139._jpeg(raw)
                errors.append(f"empty image size={body.get('size')} quality={body.get('quality')}")
            except Exception as exc:
                errors.append(v139._safe_error(exc))
    raise RuntimeError("OpenAI scene generation failed: " + " | ".join(errors[-4:])[:900])


async def _make_scene_candidates(mod: Any, scene: str, aspect: str, debug: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    jobs: list[tuple[str, str, Callable[[], Awaitable[bytes]]]] = []

    if v139.selfie.previous._gemini_key(mod) and _flag("CELEBRITY_V139_GEMINI_SCENE_ENABLED", True):
        models = v139.selfie.previous._gemini_models(mod)
        count = _integer("CELEBRITY_V139_GEMINI_SCENES", 2, 0, 4)
        for index in range(count):
            model = models[index % len(models)] if models else "gemini-3-pro-image"
            jobs.append((
                f"scene_gemini_{index + 1}",
                f"gemini:{model}",
                lambda model=model, index=index: _gemini_scene_direct(mod, model, v139._scene_prompt(scene, aspect, index), aspect),
            ))

    if v139.selfie._openai_key(mod) and _flag("CELEBRITY_V139_OPENAI_SCENE_ENABLED", True):
        jobs.append((
            "scene_openai_1",
            "openai:official-images",
            lambda: _openai_scene_direct(mod, v139._scene_prompt(scene, aspect, 2), aspect),
        ))

    if v139.selfie._bfl_key() and _flag("CELEBRITY_V139_FLUX_SCENE_ENABLED", True):
        jobs.append((
            "scene_flux_1",
            f"bfl:{os.environ.get('CELEBRITY_FLUX_MODEL') or 'flux-2-pro'}",
            lambda: v139.selfie._flux_edit(v139._scene_prompt(scene, aspect, 1), [], aspect),
        ))

    semaphore = asyncio.Semaphore(_integer("CELEBRITY_V139_SCENE_PARALLEL", 2, 1, 3))

    async def run_job(name: str, provider: str, factory: Callable[[], Awaitable[bytes]]) -> None:
        async with semaphore:
            stage = v139._stage_start(debug, name, provider)
            try:
                raw = await factory()
                problem = _soft_scene_problem(raw, name)
                if problem:
                    raise v139.PipelineError("structural_qc", problem)
                score = v139._structural_score(raw)
                candidate = {"label": name, "provider": provider, "score": score, "output": raw}
                candidates.append(candidate)
                debug["scene_candidates"].append({key: value for key, value in candidate.items() if key != "output"})
                v139._stage_finish(stage, "ok", score=score, bytes=len(raw))
            except Exception as exc:
                v139._record_error(debug, stage, exc)

    if jobs:
        await asyncio.gather(*(run_job(*job) for job in jobs))
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


async def _rescue_scene_candidate(
    mod: Any,
    user_refs: list[bytes],
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    aspect: str,
    debug: dict[str, Any],
) -> dict[str, Any] | None:
    if not _flag("CELEBRITY_V140_RESCUE_SCENE", True) or not v139.selfie._openai_key(mod):
        return None
    stage = v139._stage_start(debug, "scene_rescue_openai_candidate", "openai:known-working-candidate")
    try:
        raw = await v139.selfie._openai_candidate(
            mod,
            user_refs[0],
            user_refs[1:],
            celebrity_refs[0],
            celebrity_refs,
            celebrity_name,
            scene,
            aspect,
        )
        problem = _soft_scene_problem(raw, "scene-rescue")
        if problem:
            raise v139.PipelineError("structural_qc", problem)
        score = v139._structural_score(raw)
        row = {"label": "scene_rescue_openai_candidate", "provider": "openai:known-working-candidate", "score": score, "output": raw}
        debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
        v139._stage_finish(stage, "ok", score=score, bytes=len(raw))
        return row
    except Exception as exc:
        v139._record_error(debug, stage, exc)
        return None


async def _run_v140_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    if not user_photo:
        raise v139.PipelineError("input", "User selfie is missing")
    if not celebrity_refs:
        raise v139.PipelineError("input", "Public-person references are missing")

    aspect = v139.selfie._aspect_for_scene(scene)
    debug = v139._new_debug(celebrity_name, scene, aspect)
    debug["version"] = VERSION
    debug["scene_rescue"] = "enabled"
    user_refs = [user_photo, *[raw for raw in (additional_user_refs or []) if raw]]
    best_public_ref = await v139.selfie.impl._best_reference(celebrity_refs)
    public_refs = [best_public_ref, *[raw for raw in celebrity_refs if raw is not best_public_ref]]

    try:
        if previous_result:
            problem = v139._structural_problem(previous_result, "previous-result")
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            scenes = [{"label": "accepted_previous_scene", "provider": "previous", "score": v139._structural_score(previous_result), "output": previous_result}]
            debug["scene_candidates"].append({key: value for key, value in scenes[0].items() if key != "output"})
        else:
            scenes = await _make_scene_candidates(mod, scene, aspect, debug)

        if not scenes:
            rescue = await _rescue_scene_candidate(mod, user_refs, public_refs, celebrity_name, scene, aspect, debug)
            if rescue:
                scenes = [rescue]

        finals: list[dict[str, Any]] = []
        if scenes:
            scene_limit = _integer("CELEBRITY_V139_SCENES_TO_IDENTITY", 2, 1, 3)
            for scene_candidate in scenes[:scene_limit]:
                finals.extend(await v139._process_scene(mod, scene_candidate, user_refs, public_refs, celebrity_name, aspect, debug))

        if not finals:
            emergency = await v139._emergency_one_shot(mod, user_refs, public_refs, celebrity_name, scene, aspect, debug)
            if emergency:
                finals.append(emergency)

        if not finals:
            categories = [str(item.get("category") or "") for item in debug.get("errors", [])]
            if not scenes:
                category = "scene_generation"
                message = "No scene provider or rescue route returned an image"
            else:
                category = "identity_providers" if any(item in categories for item in ("auth_or_key", "provider_error", "timeout", "rate_limit")) else "identity_pipeline"
                message = "Scene drafts existed, but no identity-locked result survived"
            debug["failure_class"] = category
            raise v139.PipelineError(category, message, debug=debug)

        finals.sort(key=lambda item: float(item.get("total") or 0), reverse=True)
        best = await v139._repair_weak_side(mod, finals[0], user_refs, public_refs, celebrity_name, aspect, debug)
        debug["selected"] = {key: value for key, value in best.items() if key != "output"}
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        debug["failure_class"] = None
        public = v139._public_debug(debug)
        v139._LAST_RUN_DEBUG = public
        return best["output"], public
    except v139.PipelineError as exc:
        debug["failure_class"] = exc.category
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        public = v139._public_debug(debug)
        v139._LAST_RUN_DEBUG = public
        exc.debug = public
        raise
    except Exception as exc:
        category = v139._classify_error(exc)
        debug["failure_class"] = category
        debug["errors"].append({"stage": "pipeline", "provider": "internal", "category": category, "error": v139._safe_error(exc)})
        debug["finished_at"] = time.time()
        debug["duration_s"] = round(debug["finished_at"] - debug["started_at"], 2)
        public = v139._public_debug(debug)
        v139._LAST_RUN_DEBUG = public
        raise v139.PipelineError(category, v139._safe_error(exc), debug=public) from exc


def _failure_message(exc: BaseException, debug: dict[str, Any]) -> str:
    base = _ORIGINAL_FAILURE_MESSAGE(exc, debug)
    errors = list(debug.get("errors") or [])
    if not errors:
        return base
    details: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in reversed(errors):
        provider = str(item.get("provider") or "-")
        category = str(item.get("category") or "provider_error")
        key = (provider, category)
        if key in seen:
            continue
        seen.add(key)
        stage = str(item.get("stage") or "-")
        text = str(item.get("error") or "").replace("\n", " ")[:180]
        details.append(f"{stage}/{provider}: {category} — {text}")
        if len(details) >= 3:
            break
    return base + ("\nПричины: " + " | ".join(reversed(details)) if details else "")


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
    output, _ = await _run_v140_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def install() -> None:
    os.environ.setdefault("CELEBRITY_V140_SOFT_ONE_FACE_SCENE_GATE", "1")
    os.environ.setdefault("CELEBRITY_V140_RESCUE_SCENE", "1")
    os.environ.setdefault("CELEBRITY_V140_GEMINI_TIMEOUT_S", "420")
    os.environ.setdefault("CELEBRITY_V140_OPENAI_TIMEOUT_S", "420")

    v139.VERSION = VERSION
    v139._make_scene_candidates = _make_scene_candidates
    v139._run_two_stage_generation = _run_v140_generation
    v139._run_compat = _run_compat
    v139._failure_message = _failure_message

    v139.selfie._run_v139_generation = _run_v140_generation
    v139.selfie._run_v140_generation = _run_v140_generation
    v139.selfie._generate = v139._generate
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._generate = v139._generate
    v139.selfie.engine._diag = v139._diag


install()

__all__ = [
    "VERSION",
    "install",
    "_gemini_scene_direct",
    "_openai_scene_direct",
    "_make_scene_candidates",
    "_rescue_scene_candidate",
    "_run_v140_generation",
    "_failure_message",
]
