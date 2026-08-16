# -*- coding: utf-8 -*-
"""V291 memory-safe camera-gaze identity transfer and single-flight guard.

This supersedes the V290/V290b oversized working-canvas experiment. The previous
1800/1900px local canvases could keep several RGB/PIL/OpenCV copies alive at once
while the full Gemini composition and Telegram payloads were also resident. On the
Render Starter instance that is enough to cross the memory limit and restart the
service mid-generation.

Production rules:
- keep the proven V289b deterministic local identity path as the primary path;
- never upscale a crop more than 2x and never exceed a small bounded pixel budget;
- prefer native crops when they already contain enough facial information;
- preserve the generated target eye region so selfie gaze remains lens-directed;
- aggressively release temporary image buffers after the identity stage;
- keep duplicate callback / concurrent generation suppression.
"""
from __future__ import annotations

import contextlib
import gc
import time
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v277_production_fidelity_patch as fidelity
from neyrobot_prod import selfie_v289_native_identity_primary as v289

VERSION = "v291-memory-safe-native-gaze-singleflight-2026-08-16"
_INSTALLED = False
_ORIGINAL_PROMPT = terminal._prompt
_ORIGINAL_GENERATE = terminal.generate
_REMOTE_FALLBACK = v289._ORIGINAL_IDENTITY_SWAP

_SEEN: dict[str, float] = {}
_ACTIVE_USERS: dict[int, float] = {}
_TTL = 20.0 * 60.0


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    text = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    label = str(shot_label or "").lower()
    if "селфи" in label or "selfie" in label:
        text += (
            " CAMERA-GAZE CONTRACT — NON-NEGOTIABLE: both principal people must look directly into the invisible front-camera lens at capture time. "
            "PERSON A's pupils/irises must be naturally aimed at the lens, with normal eye convergence for a close phone selfie. "
            "The user's reference photos define identity, anatomy, age and texture, but DO NOT define gaze direction; never copy an off-camera glance from a reference. "
            "PERSON B must also look into the same lens. Keep eyes anatomically natural: no cross-eye, no frozen stare, no enlarged irises, no asymmetrical pupil direction."
        )
    else:
        text += (
            " CAMERA-GAZE CONTRACT: unless the requested scene explicitly requires otherwise, both principal people should naturally look toward the photographing camera. "
            "Reference-photo gaze direction is not authoritative."
        )
    return text


def _resize_exact(raw: bytes, size: tuple[int, int], *, sharpen: bool = False) -> bytes:
    from PIL import Image, ImageFilter

    img = fs.image(raw).convert("RGB")
    try:
        if img.size != size:
            resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            img = img.resize(size, resampling)
        if sharpen:
            img = img.filter(ImageFilter.UnsharpMask(radius=0.36, percent=42, threshold=4))
        out = BytesIO()
        img.save(out, "JPEG", quality=98, subsampling=0, optimize=True, progressive=False)
        return out.getvalue()
    finally:
        with contextlib.suppress(Exception):
            img.close()


def _bounded_work_canvas(raw: bytes, *, min_long_side: int, max_scale: float = 2.0, max_pixels: int = 1_450_000) -> bytes:
    """Create a modest working canvas without the V290 multi-megapixel RAM spike."""
    from PIL import Image, ImageFilter

    img = fs.image(raw).convert("RGB")
    try:
        w, h = img.size
        long_side = max(w, h)
        if long_side >= min_long_side:
            return raw

        scale = min(max_scale, float(min_long_side) / float(max(1, long_side)))
        # Hard pixel-budget clamp. This matters more than JPEG byte size because PIL
        # and OpenCV expand images into several raw RGB/array copies in memory.
        projected = float(w * h) * scale * scale
        if projected > float(max_pixels):
            scale = min(scale, (float(max_pixels) / float(max(1, w * h))) ** 0.5)
        if scale <= 1.04:
            return raw

        size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        resized = img.resize(size, resampling)
        try:
            resized = resized.filter(ImageFilter.UnsharpMask(radius=0.32, percent=28, threshold=5))
            out = BytesIO()
            resized.save(out, "JPEG", quality=98, subsampling=0, optimize=True, progressive=False)
            return out.getvalue()
        finally:
            with contextlib.suppress(Exception):
                resized.close()
    finally:
        with contextlib.suppress(Exception):
            img.close()


def _preserve_camera_gaze(target_raw: bytes, identity_raw: bytes, log: Any, *, trace: str) -> bytes:
    """Blend only the target eye/iris region back over the identity result."""
    from PIL import Image, ImageDraw, ImageFilter

    target = fs.image(target_raw).convert("RGB")
    identity = fs.image(identity_raw).convert("RGB")
    try:
        if identity.size != target.size:
            resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized_identity = identity.resize(target.size, resampling)
            identity.close()
            identity = resized_identity

        try:
            face = fs.source_face_crop(target_raw, None)
            fx, fy, fw, fh = [float(v) for v in face.face_box]
        except Exception as exc:
            log("AI_SELFIE_V291_GAZE trace=%s status=skip reason=face_detection error=%s", trace, str(exc)[:300])
            return identity_raw

        centers = [
            (fx + fw * 0.315, fy + fh * 0.405),
            (fx + fw * 0.685, fy + fh * 0.405),
        ]
        eye_w = max(18.0, fw * 0.205)
        eye_h = max(10.0, fh * 0.095)
        mask = Image.new("L", target.size, 0)
        try:
            draw = ImageDraw.Draw(mask)
            for cx, cy in centers:
                draw.ellipse((cx - eye_w / 2.0, cy - eye_h / 2.0, cx + eye_w / 2.0, cy + eye_h / 2.0), fill=235)
            blurred = mask.filter(ImageFilter.GaussianBlur(max(1.0, fw * 0.008)))
            try:
                merged = Image.composite(target, identity, blurred)
                try:
                    out = BytesIO()
                    merged.save(out, "JPEG", quality=98, subsampling=0, optimize=True, progressive=False)
                    payload = out.getvalue()
                finally:
                    merged.close()
            finally:
                blurred.close()
        finally:
            mask.close()

        log(
            "AI_SELFIE_V291_GAZE trace=%s status=applied face=%s target_sha=%s identity_sha=%s out_sha=%s",
            trace, face.face_box, fs.sha(target_raw), fs.sha(identity_raw), fs.sha(payload),
        )
        return payload
    finally:
        with contextlib.suppress(Exception):
            target.close()
        with contextlib.suppress(Exception):
            identity.close()


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    safe, reason = v289._local_gate(target_crop, source_crop, log, trace=trace)
    if not safe:
        log("AI_SELFIE_V291_IDENTITY trace=%s stage=local_gate_failed fallback=remote_stack reason=%s", trace, reason)
        return await _REMOTE_FALLBACK(target_crop, source_crop, log, trace=trace)

    # First use the proven V289b native path. It already knows how to fall back safely
    # when local evidence is insufficient. This avoids allocating giant V290 canvases.
    try:
        candidate, provider = await v289._identity_swap(target_crop, source_crop, log, trace=trace)
        if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
            raise RuntimeError("V289b returned unchanged/empty target")

        # Keep camera-directed eyes from the generated composition. This is cheap at
        # native target-crop size and does not invoke another model/provider.
        with contextlib.suppress(Exception):
            candidate = _preserve_camera_gaze(target_crop, candidate, log, trace=trace)

        # Mild native-size finishing only; no 4x/1900px canvas.
        native_size = fs.image(target_crop).size
        candidate = _resize_exact(candidate, native_size, sharpen=True)
        log(
            "AI_SELFIE_V291_IDENTITY trace=%s stage=native_primary_success provider=%s remote_provider=%s target=%s source=%s out=%s memory_profile=native",
            trace, provider, "true" if "piapi" in provider or "replicate" in provider else "false", fs.dims(target_crop), fs.dims(source_crop), fs.dims(candidate),
        )
        return candidate, provider + "+v291_camera_gaze"
    except Exception as native_exc:
        log(
            "AI_SELFIE_V291_IDENTITY trace=%s stage=native_primary_failed error_type=%s error=%s fallback=bounded_local",
            trace, type(native_exc).__name__, str(native_exc)[:700],
        )

    # A bounded second local attempt can improve a genuinely tiny target without the
    # previous 1800/1900px memory explosion. Target <= ~900 long side, source <= ~1100.
    target_work = source_work = candidate_work = None
    try:
        target_work = _bounded_work_canvas(target_crop, min_long_side=900, max_scale=2.0, max_pixels=1_050_000)
        source_work = _bounded_work_canvas(source_crop, min_long_side=1100, max_scale=1.6, max_pixels=1_450_000)
        log(
            "AI_SELFIE_V291_MEMORY trace=%s stage=bounded_prepare target_native=%s target_work=%s source_native=%s source_work=%s",
            trace, fs.dims(target_crop), fs.dims(target_work), fs.dims(source_crop), fs.dims(source_work),
        )
        candidate_work, meta = fidelity._source_native_face_core(source_work, target_work, log, trace=trace)
        if len(candidate_work) < 1024 or fs.sha(candidate_work) == fs.sha(target_work):
            raise RuntimeError("bounded local core returned unchanged/empty target")

        with contextlib.suppress(Exception):
            candidate_work = _preserve_camera_gaze(target_work, candidate_work, log, trace=trace)
        native_size = fs.image(target_crop).size
        candidate = _resize_exact(candidate_work, native_size, sharpen=True)
        geometry_ok, geometry_reason = v289._geometry_status(target_crop, candidate, log, trace=trace)
        if not geometry_ok:
            raise RuntimeError(f"bounded local geometry change: {geometry_reason}")
        log(
            "AI_SELFIE_V291_IDENTITY trace=%s stage=bounded_local_success mode=%s out=%s remote_provider=false memory_profile=bounded",
            trace, meta.get("mode"), fs.dims(candidate),
        )
        return candidate, "source_native_face_core_v291_bounded_camera_gaze"
    except Exception as bounded_exc:
        log(
            "AI_SELFIE_V291_IDENTITY trace=%s stage=bounded_local_failed error_type=%s error=%s fallback=remote_last_resort",
            trace, type(bounded_exc).__name__, str(bounded_exc)[:700],
        )
        return await _REMOTE_FALLBACK(target_crop, source_crop, log, trace=trace)
    finally:
        # Bytes objects are released as soon as this stage ends; explicit GC is useful
        # here because PIL/OpenCV temporary arrays may otherwise survive until a later
        # collection while the full composition is still resident.
        target_work = None
        source_work = None
        candidate_work = None
        gc.collect()


def _event_key(update: Any, user_id: int) -> str:
    callback = getattr(update, "callback_query", None)
    callback_id = str(getattr(callback, "id", "") or "")
    if callback_id:
        return f"cb:{user_id}:{callback_id}"
    update_id = getattr(update, "update_id", None)
    if update_id is not None:
        return f"upd:{user_id}:{update_id}"
    message = getattr(update, "effective_message", None)
    message_id = getattr(message, "message_id", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", 0)
    return f"msg:{user_id}:{chat_id}:{message_id}"


def _purge(now: float) -> None:
    for key, ts in list(_SEEN.items()):
        if now - ts > _TTL:
            _SEEN.pop(key, None)
    for uid, ts in list(_ACTIVE_USERS.items()):
        if now - ts > _TTL:
            _ACTIVE_USERS.pop(uid, None)


async def _generate_singleflight(update: Any, context: Any, scene: str = "") -> bool:
    user = getattr(update, "effective_user", None)
    user_id = int(getattr(user, "id", 0) or 0)
    now = time.monotonic()
    _purge(now)
    key = _event_key(update, user_id)

    if key in _SEEN:
        _log("AI_SELFIE_V291_SINGLEFLIGHT status=duplicate_callback_suppressed user_id=%s key=%s", user_id, key)
        return True
    if user_id and user_id in _ACTIVE_USERS:
        _SEEN[key] = now
        _log("AI_SELFIE_V291_SINGLEFLIGHT status=concurrent_generation_suppressed user_id=%s key=%s", user_id, key)
        return True

    _SEEN[key] = now
    if user_id:
        _ACTIVE_USERS[user_id] = now
    _log("AI_SELFIE_V291_SINGLEFLIGHT status=acquired user_id=%s key=%s", user_id, key)
    try:
        return bool(await _ORIGINAL_GENERATE(update, context, scene))
    finally:
        if user_id:
            _ACTIVE_USERS.pop(user_id, None)
        gc.collect()
        _log("AI_SELFIE_V291_SINGLEFLIGHT status=released user_id=%s key=%s", user_id, key)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._prompt = _prompt
    terminal._identity_swap = _identity_swap
    terminal.generate = _generate_singleflight
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V291"
    setattr(terminal, "_v291_camera_gaze", True)
    setattr(terminal, "_v291_memory_safe_identity", True)
    setattr(terminal, "_v291_singleflight", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V291 memory-safe native gaze + singleflight installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
