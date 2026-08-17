# -*- coding: utf-8 -*-
"""V301 production AI Selfie: fast source detection + resilient bounded Stage-1.

V300 correctly blocked the historical outer composition retries, but production
traces still showed two independent latency/reliability problems:
1) source preparation could spend ~45-50 s in the exhaustive multi-cascade face
   detector even for a clean near-frontal portrait;
2) Gemini Flash could time out and Gemini Pro could return HTTP 500 in the same
   bounded Stage-1, leaving the job with no composition.

V301 fixes both without changing the identity-transfer or final integration path:
- photo #3 uses a lightweight downscaled frontal/profile detector first;
- Stage-1 sends a compact reference set instead of every redundant reference;
- Gemini Flash gets one short bounded attempt;
- when an official OpenAI image key is configured, OpenAI image generation is a
  cross-provider fallback inside the same production budget;
- Gemini Pro is retained only as the fallback when OpenAI Images is unavailable;
- outer attempts 2/3 remain provider-free and fail immediately.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import re
import time
from typing import Any

from neyrobot_prod import celebrity_selfie as base
from neyrobot_prod import celebrity_selfie_v204 as extractor
from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v211_delivery as delivery
from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v287_first_pass_quality as v287
from neyrobot_prod import selfie_v293_selfie_composition_gate as v293

VERSION = "v301-fast-source-cross-provider-stage1-2026-08-17"
_INSTALLED = False

_PREV_GOOGLE_CALL = v229._call_google
_PREV_SOURCE = terminal._source
_PREV_TARGET = terminal._target


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _stage_attempt(stage: str) -> int:
    match = re.search(r"scene_hero_body_attempt_(\d+)", str(stage or ""))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _budget_s() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_TOTAL_BUDGET_S") or "78")
    except Exception:
        value = 78.0
    return max(55.0, min(95.0, value))


def _gemini_flash_s() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_FLASH_TIMEOUT_S") or "28")
    except Exception:
        value = 28.0
    return max(18.0, min(38.0, value))


def _fallback_s() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_FALLBACK_TIMEOUT_S") or "48")
    except Exception:
        value = 48.0
    return max(30.0, min(60.0, value))


def _official_openai_key() -> str:
    key = str(os.getenv("OPENAI_IMAGE_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key or key.startswith("sk-or-"):
        return ""
    return key


def _select_refs(labeled_images: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Keep the information Stage-1 actually needs, capped to five images."""
    if len(labeled_images) <= 5:
        return [(str(label), bytes(raw or b"")) for label, raw in labeled_images]

    scene: list[tuple[str, bytes]] = []
    user: list[tuple[str, bytes]] = []
    hero: list[tuple[str, bytes]] = []
    other: list[tuple[str, bytes]] = []
    for label, raw in labeled_images:
        item = (str(label), bytes(raw or b""))
        upper = str(label).upper()
        if "AUTHORITATIVE LOCATION" in upper or "SCENE" in upper or "LOCATION" in upper:
            scene.append(item)
        elif "USER AGE/BUILD" in upper or "USER BODY" in upper:
            user.append(item)
        elif "HERO" in upper or "CELEBRITY" in upper or "PERSON B" in upper:
            hero.append(item)
        else:
            other.append(item)

    selected: list[tuple[str, bytes]] = []
    if scene:
        selected.append(scene[0])
    selected.extend(user[:2])
    selected.extend(hero[:2])
    for item in other + user[2:] + hero[2:] + scene[1:]:
        if len(selected) >= 5:
            break
        selected.append(item)
    if not selected:
        selected = [(str(label), bytes(raw or b"")) for label, raw in labeled_images[:5]]
    return selected[:5]


def _prepare_gemini_refs(labeled_images: list[tuple[str, bytes]]) -> list[tuple[str, str, str]]:
    prepared: list[tuple[str, str, str]] = []
    for label, raw in _select_refs(labeled_images):
        data = bytes(raw or b"")
        if "USER AGE/BUILD" in label.upper() or "USER BODY" in label.upper():
            with contextlib.suppress(Exception):
                data = v287._upper_body_reference(data)
            label = label + " CAMERA-FRAMING NOTE: use only age/build/proportions; ignore source camera distance and face identity."
        encoded, mime = v229._prepare(data)
        prepared.append((label, encoded, mime))
    return prepared


def _fast_source(photo3: bytes, log: Any) -> fs.FaceTarget:
    """Fast source detector for clean portrait #3; legacy exhaustive detector is last resort."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        img = fs.image(photo3)
        iw, ih = img.size
        max_side = max(iw, ih)
        scale = min(1.0, 720.0 / float(max(1, max_side)))
        sw, sh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
        rgb = np.asarray(img)
        if scale < 0.999:
            rgb = cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        equalized = cv2.equalizeHist(gray)
        min_side = max(44, int(min(sw, sh) * 0.075))

        hits: list[tuple[int, int, int, int, int]] = []
        for idx, name in enumerate(("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")):
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + name)
            if cascade.empty():
                continue
            frame = gray if idx == 0 else equalized
            found = cascade.detectMultiScale(frame, scaleFactor=1.09, minNeighbors=4, minSize=(min_side, min_side))
            for x, y, w, h in found:
                hits.append((int(x), int(y), int(w), int(h), 2 - idx))

        if not hits:
            profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
            if not profile.empty():
                for mirrored in (False, True):
                    frame = cv2.flip(equalized, 1) if mirrored else equalized
                    found = profile.detectMultiScale(frame, scaleFactor=1.10, minNeighbors=4, minSize=(min_side, min_side))
                    for x, y, w, h in found:
                        if mirrored:
                            x = sw - int(x) - int(w)
                        hits.append((int(x), int(y), int(w), int(h), 0))

        if not hits:
            raise ValueError("fast detector found no face")

        cx0, cy0 = sw / 2.0, sh * 0.43
        def rank(hit: tuple[int, int, int, int, int]) -> float:
            x, y, w, h, support = hit
            cx, cy = x + w / 2.0, y + h / 2.0
            center_penalty = ((cx - cx0) / max(1.0, sw)) ** 2 + ((cy - cy0) / max(1.0, sh)) ** 2
            return float(w * h) * (1.0 + 0.08 * support) - center_penalty * float(sw * sh) * 0.25

        x, y, w, h, support = max(hits, key=rank)
        inv = 1.0 / scale
        box = (
            max(0, int(round(x * inv))),
            max(0, int(round(y * inv))),
            max(1, int(round(w * inv))),
            max(1, int(round(h * inv))),
        )
        if box[2] < 90 or box[3] < 90:
            raise ValueError("fast source face too small")

        crop_box = fs._expand(box, img.size, 1.42, 1.56, 0.015)
        crop_img = img.crop(crop_box)
        raw = fs.jpeg(crop_img, max_side=1800, quality=99)
        fw, fh = box[2], box[3]
        cw, ch = crop_img.size
        face_w_coverage = fw / float(max(1, cw))
        face_h_coverage = fh / float(max(1, ch))
        if face_w_coverage < 0.54 or face_h_coverage < 0.48:
            raise ValueError("fast source crop not face-centric enough")
        result = fs.FaceTarget(box, crop_box, raw, int(max(1, support)), 0, float(fw * fh))
        log(
            "AI_SELFIE_V301_SOURCE status=fast face=%s crop=%s dims=%s support=%s face_w_coverage=%.3f face_h_coverage=%.3f",
            result.face_box, result.crop_box, fs.dims(raw), result.support, face_w_coverage, face_h_coverage,
        )
        return result
    except Exception as exc:
        log(
            "AI_SELFIE_V301_SOURCE status=fast_failed error_type=%s error=%s fallback=legacy",
            type(exc).__name__, str(exc)[:300],
        )
        return _PREV_SOURCE(photo3, log)


async def _gemini_flash_once(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str, timeout_s: float) -> tuple[bytes, str]:
    import httpx

    key = v229._key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")
    configured = [str(x).strip() for x in v229._models() if str(x).strip()]
    flash = next((m for m in configured if "flash" in m.lower()), configured[0] if configured else "gemini-3.1-flash-image")
    prepared = _prepare_gemini_refs(labeled_images)
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, encoded, mime in prepared:
        parts.append({"text": label})
        parts.append({"inlineData": {"mimeType": mime, "data": encoded}})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": base._aspect_ratio(), "imageSize": "1K"},
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    timeout = httpx.Timeout(timeout_s, connect=min(8.0, timeout_s), read=timeout_s, write=min(20.0, timeout_s), pool=8.0)
    started = time.monotonic()
    _log("AI_SELFIE_V301_STAGE1 stage=%s provider=gemini model=%s status=enter refs=%s timeout=%.0fs", stage, flash, len(prepared), timeout_s)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await asyncio.wait_for(
            client.post(f"{v229._base_url()}/models/{flash}:generateContent", headers=headers, json=payload),
            timeout=timeout_s + 1.0,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini Flash HTTP {response.status_code}: {response.text[:320]}")
    output = extractor._extract_final_image(response.json())
    if not output or len(output) <= 1024:
        raise RuntimeError("Gemini Flash returned no final image")
    _log("AI_SELFIE_V301_STAGE1 stage=%s provider=gemini model=%s status=success elapsed=%.2fs bytes=%s", stage, flash, time.monotonic() - started, len(output))
    return bytes(output), flash


async def _openai_image_fallback(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str, timeout_s: float) -> tuple[bytes, str]:
    import httpx

    key = _official_openai_key()
    if not key:
        raise RuntimeError("official OpenAI image key is unavailable")
    refs = _select_refs(labeled_images)
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt + "\nGenerate the final vertical photograph now. Do not return an explanation."}]
    for label, raw in refs:
        encoded, mime = v229._prepare(raw)
        content.append({"type": "input_text", "text": str(label)})
        content.append({"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"})

    image_model = str(os.getenv("AI_SELFIE_OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
    orchestrator = str(os.getenv("AI_SELFIE_OPENAI_RESPONSE_MODEL") or "gpt-5-mini").strip()
    quality = str(os.getenv("AI_SELFIE_OPENAI_IMAGE_QUALITY") or "low").strip().lower()
    if quality not in {"low", "medium", "high", "auto"}:
        quality = "low"
    payload = {
        "model": orchestrator,
        "input": [{"role": "user", "content": content}],
        "tools": [{
            "type": "image_generation",
            "model": image_model,
            "quality": quality,
            "size": "1024x1536",
            "background": "opaque",
        }],
        "tool_choice": "required",
        "store": False,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"}
    base_url = str(os.getenv("OPENAI_IMAGES_BASE_URL") or os.getenv("IMAGES_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    started = time.monotonic()
    timeout = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s), read=timeout_s, write=min(25.0, timeout_s), pool=10.0)
    _log("AI_SELFIE_V301_STAGE1 stage=%s provider=openai status=enter model=%s orchestrator=%s refs=%s timeout=%.0fs quality=%s", stage, image_model, orchestrator, len(refs), timeout_s, quality)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await asyncio.wait_for(
            client.post(f"{base_url}/responses", headers=headers, json=payload),
            timeout=timeout_s + 1.0,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI image fallback HTTP {response.status_code}: {response.text[:380]}")
    js = response.json() or {}
    for item in js.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "image_generation_call" and item.get("result"):
            raw = base64.b64decode(item["result"])
            if len(raw) > 1024:
                _log("AI_SELFIE_V301_STAGE1 stage=%s provider=openai status=success elapsed=%.2fs bytes=%s", stage, time.monotonic() - started, len(raw))
                return raw, f"openai_{image_model}"
    raise RuntimeError("OpenAI image fallback returned no image_generation_call result")


async def _gemini_pro_fallback(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str, timeout_s: float) -> tuple[bytes, str]:
    import httpx

    key = v229._key()
    configured = [str(x).strip() for x in v229._models() if str(x).strip()]
    pro = next((m for m in configured if "pro" in m.lower()), "gemini-3-pro-image")
    prepared = _prepare_gemini_refs(labeled_images)
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, encoded, mime in prepared:
        parts.append({"text": label})
        parts.append({"inlineData": {"mimeType": mime, "data": encoded}})
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    timeout = httpx.Timeout(timeout_s, connect=min(8.0, timeout_s), read=timeout_s, write=min(20.0, timeout_s), pool=8.0)
    _log("AI_SELFIE_V301_STAGE1 stage=%s provider=gemini_fallback model=%s status=enter refs=%s timeout=%.0fs compatibility=true", stage, pro, len(prepared), timeout_s)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await asyncio.wait_for(client.post(f"{v229._base_url()}/models/{pro}:generateContent", headers=headers, json=payload), timeout=timeout_s + 1.0)
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini Pro fallback HTTP {response.status_code}: {response.text[:320]}")
    output = extractor._extract_final_image(response.json())
    if not output or len(output) <= 1024:
        raise RuntimeError("Gemini Pro fallback returned no final image")
    return bytes(output), pro


async def _call_stage1_v301(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    attempt = _stage_attempt(stage)
    is_selfie = bool(attempt and v293._is_selfie_prompt(prompt))
    if not is_selfie:
        return await _PREV_GOOGLE_CALL(prompt, labeled_images, stage)

    task = asyncio.current_task()
    if task is not None:
        setattr(task, "_ai_selfie_v301_job", True)
        cached = getattr(task, "_ai_selfie_v301_composition", None)
        cached_model = getattr(task, "_ai_selfie_v301_model", None)
        if isinstance(cached, (bytes, bytearray)) and len(cached) > 1024:
            _log("AI_SELFIE_V301_STAGE1 stage=%s status=reuse_composition attempt=%s provider_call=false", stage, attempt)
            return bytes(cached), str(cached_model or "v301_cached")
        first_error = getattr(task, "_ai_selfie_v301_first_error", None)
        if attempt > 1 and first_error:
            _log("AI_SELFIE_V301_STAGE1 stage=%s status=outer_retry_blocked attempt=%s provider_call=false", stage, attempt)
            raise RuntimeError(str(first_error))

    total_budget = _budget_s()
    started = time.monotonic()
    errors: list[str] = []
    selected_count = len(_select_refs(labeled_images))
    _log("AI_SELFIE_V301_STAGE1 stage=%s status=plan refs_in=%s refs_selected=%s total_budget=%.0fs openai_fallback=%s", stage, len(labeled_images), selected_count, total_budget, bool(_official_openai_key()))

    try:
        try:
            output, model = await _gemini_flash_once(prompt, labeled_images, stage, min(_gemini_flash_s(), total_budget - 2.0))
        except Exception as exc:
            errors.append(f"gemini_flash:{type(exc).__name__}:{str(exc)[:240]}")
            _log("AI_SELFIE_V301_STAGE1 stage=%s provider=gemini status=failed error_type=%s error=%s", stage, type(exc).__name__, str(exc)[:300])
            elapsed = time.monotonic() - started
            remaining = total_budget - elapsed
            if remaining < 12.0:
                raise RuntimeError("Stage-1 budget exhausted after Gemini Flash") from exc
            if _official_openai_key():
                output, model = await _openai_image_fallback(prompt, labeled_images, stage, min(_fallback_s(), max(12.0, remaining - 1.0)))
            else:
                output, model = await _gemini_pro_fallback(prompt, labeled_images, stage, min(_fallback_s(), max(12.0, remaining - 1.0)))

        if task is not None:
            setattr(task, "_ai_selfie_v301_composition", bytes(output))
            setattr(task, "_ai_selfie_v301_model", str(model))
        _log("AI_SELFIE_V301_STAGE1 stage=%s status=composition_ready provider=%s elapsed=%.2fs bytes=%s", stage, model, time.monotonic() - started, len(output))
        return output, model
    except Exception as exc:
        errors.append(f"fallback:{type(exc).__name__}:{str(exc)[:300]}")
        message = " | ".join(errors[-3:])
        if task is not None:
            setattr(task, "_ai_selfie_v301_first_error", message)
        _log("AI_SELFIE_V301_STAGE1 stage=%s status=failed elapsed=%.2fs errors=%s outer_retry_blocked=true", stage, time.monotonic() - started, message[:700])
        raise RuntimeError(message) from exc


def _target_v301(composition: bytes, *, scene_image: bool, log: Any):
    task = asyncio.current_task()
    if not (task is not None and getattr(task, "_ai_selfie_v301_job", False)):
        return _PREV_TARGET(composition, scene_image=scene_image, log=log)
    try:
        base_img, target, metrics = v287._first_pass_target(composition, log)
        metrics = dict(metrics)
        metrics["v301_single_stage1"] = 1.0
        metrics["v301_regeneration_for_distance"] = 0.0
        log("AI_SELFIE_V301_TARGET status=accepted face=%s crop=%s dims=%s regeneration=false", target.face_box, target.crop_box, getattr(base_img, "size", None))
        return base_img, target, metrics
    except Exception as exc:
        log("AI_SELFIE_V301_TARGET status=first_pass_failed error_type=%s error=%s fallback=previous_target", type(exc).__name__, str(exc)[:400])
        return _PREV_TARGET(composition, scene_image=scene_image, log=log)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._source = _fast_source
    v229._call_google = _call_stage1_v301
    terminal._target = _target_v301
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V301"
    setattr(terminal, "_v301_fast_source", True)
    setattr(terminal, "_v301_cross_provider_stage1", True)
    setattr(terminal, "_v301_outer_retry_blocked", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V301 fast source + cross-provider Stage-1 installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
