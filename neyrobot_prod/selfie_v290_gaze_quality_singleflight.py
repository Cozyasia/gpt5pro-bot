# -*- coding: utf-8 -*-
"""V290b camera-gaze, high-resolution native identity and single-flight guard.

Goals:
- PERSON A and PERSON B look into the actual shot lens in selfie mode;
- photo #3 remains the identity source, but its incidental gaze direction must not
  override the requested camera gaze;
- run the deterministic source-native facial-core transfer on a larger working
  canvas for cleaner sub-pixel geometry, then return to the exact native target size;
- preserve the target composition's eye/gaze region after identity transfer so the
  generated front-camera gaze survives the source-photo transplant;
- suppress duplicate callback execution and concurrent duplicate generation for the
  same user before billing/provider work starts;
- IMPORTANT: if the V290 hi-res enhancement itself fails after the upstream target
  and source have already passed the local gate, degrade to the proven V289b local
  identity path first. Do not jump straight into V288/PiAPI just because the optional
  hi-res/gaze enhancement had a detector or geometry hiccup.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v277_production_fidelity_patch as fidelity
from neyrobot_prod import selfie_v289_native_identity_primary as v289

VERSION = "v290b-local-first-gaze-hires-singleflight-2026-08-16"
_INSTALLED = False
_ORIGINAL_PROMPT = terminal._prompt
_ORIGINAL_GENERATE = terminal.generate
# This is intentionally the pre-V289 remote stack. It may only be used when the
# strong local source/target gate does not pass at all. A V290 enhancement failure
# must first fall back to v289._identity_swap(), which retries the authoritative
# native source-core path before considering remote providers.
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
    if img.size != size:
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize(size, resampling)
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=0.42, percent=52, threshold=3))
    out = BytesIO()
    img.save(out, "JPEG", quality=100, subsampling=0, optimize=True, progressive=False)
    return out.getvalue()


def _work_canvas(raw: bytes, min_long_side: int = 1800) -> bytes:
    """High-resolution local working canvas; no generative restoration."""
    from PIL import Image, ImageFilter

    img = fs.image(raw).convert("RGB")
    long_side = max(img.size)
    if long_side >= min_long_side:
        return raw
    scale = min(4.0, float(min_long_side) / float(max(1, long_side)))
    size = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
    resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    img = img.resize(size, resampling)
    img = img.filter(ImageFilter.UnsharpMask(radius=0.45, percent=38, threshold=4))
    out = BytesIO()
    img.save(out, "JPEG", quality=100, subsampling=0, optimize=True, progressive=False)
    return out.getvalue()


def _preserve_camera_gaze(target_raw: bytes, identity_raw: bytes, log: Any, *, trace: str) -> bytes:
    """Restore the target's eye/gaze region over the identity result."""
    from PIL import Image, ImageDraw, ImageFilter

    target = fs.image(target_raw).convert("RGB")
    identity = fs.image(identity_raw).convert("RGB")
    if identity.size != target.size:
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        identity = identity.resize(target.size, resampling)

    try:
        face = fs.source_face_crop(target_raw, None)
        fx, fy, fw, fh = [float(v) for v in face.face_box]
    except Exception as exc:
        log("AI_SELFIE_V290B_GAZE trace=%s status=skip reason=face_detection error=%s", trace, str(exc)[:300])
        return identity_raw

    centers = [
        (fx + fw * 0.315, fy + fh * 0.405),
        (fx + fw * 0.685, fy + fh * 0.405),
    ]
    eye_w = max(18.0, fw * 0.205)
    eye_h = max(10.0, fh * 0.095)
    mask = Image.new("L", target.size, 0)
    draw = ImageDraw.Draw(mask)
    for cx, cy in centers:
        draw.ellipse((cx - eye_w / 2.0, cy - eye_h / 2.0, cx + eye_w / 2.0, cy + eye_h / 2.0), fill=235)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1.2, fw * 0.009)))
    merged = Image.composite(target, identity, mask)
    out = BytesIO()
    merged.save(out, "JPEG", quality=100, subsampling=0, optimize=True, progressive=False)
    payload = out.getvalue()
    log(
        "AI_SELFIE_V290B_GAZE trace=%s status=applied face=%s eye_masks=2 target_sha=%s identity_sha=%s out_sha=%s",
        trace, face.face_box, fs.sha(target_raw), fs.sha(identity_raw), fs.sha(payload),
    )
    return payload


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    safe, reason = v289._local_gate(target_crop, source_crop, log, trace=trace)
    if safe:
        try:
            native_size = fs.image(target_crop).size
            target_hi = _work_canvas(target_crop, 1800)
            source_hi = _work_canvas(source_crop, 1900)
            log(
                "AI_SELFIE_V290B_HIRES trace=%s stage=prepare target_native=%s target_work=%s source_native=%s source_work=%s gate=%s",
                trace, fs.dims(target_crop), fs.dims(target_hi), fs.dims(source_crop), fs.dims(source_hi), reason,
            )
            candidate_hi, meta = fidelity._source_native_face_core(source_hi, target_hi, log, trace=trace)
            if len(candidate_hi) < 1024 or fs.sha(candidate_hi) == fs.sha(target_hi):
                raise RuntimeError("high-resolution native core returned unchanged/empty target")

            candidate_hi = _preserve_camera_gaze(target_hi, candidate_hi, log, trace=trace)
            candidate = _resize_exact(candidate_hi, native_size, sharpen=True)
            if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
                raise RuntimeError("V290b native identity returned unchanged/empty target")

            geometry_ok, geometry_reason = v289._geometry_status(target_crop, candidate, log, trace=trace)
            if not geometry_ok:
                raise RuntimeError(f"V290b catastrophic geometry change: {geometry_reason}")
            log(
                "AI_SELFIE_V290B_IDENTITY trace=%s stage=hires_native_success mode=%s target_native=%s source_native=%s work_target=%s work_source=%s out=%s remote_provider=false gaze=camera_target_eyes quality=hires_local",
                trace, meta.get("mode"), fs.dims(target_crop), fs.dims(source_crop), fs.dims(target_hi), fs.dims(source_hi), fs.dims(candidate),
            )
            return candidate, "source_native_face_core_v290b_hires_camera_gaze"
        except Exception as exc:
            # Critical regression fix: V290 used to jump directly to the pre-V289
            # remote stack here. That turned a harmless optional enhancement failure
            # into a PiAPI `no face found` fatal error. Retry the already-proven V289b
            # authoritative local path first, on the untouched native crops.
            log(
                "AI_SELFIE_V290B_IDENTITY trace=%s stage=hires_native_failed error_type=%s error=%s fallback=v289b_native_first",
                trace, type(exc).__name__, str(exc)[:700],
            )
            try:
                candidate, provider = await v289._identity_swap(target_crop, source_crop, log, trace=trace)
                if len(candidate) >= 1024 and fs.sha(candidate) != fs.sha(target_crop):
                    # Apply gaze preservation only if it can be localized safely. The
                    # identity result remains valid even when the eye detector is not.
                    with contextlib.suppress(Exception):
                        candidate = _preserve_camera_gaze(target_crop, candidate, log, trace=trace)
                    log(
                        "AI_SELFIE_V290B_IDENTITY trace=%s stage=v289b_native_recovery_success provider=%s remote_provider=%s out=%s",
                        trace, provider, "true" if "piapi" in provider or "replicate" in provider else "false", fs.dims(candidate),
                    )
                    return candidate, provider + "+v290b_gaze_recovery"
                raise RuntimeError("V289b recovery returned unchanged/empty target")
            except Exception as recovery_exc:
                log(
                    "AI_SELFIE_V290B_IDENTITY trace=%s stage=v289b_native_recovery_failed error_type=%s error=%s fallback=remote_last_resort",
                    trace, type(recovery_exc).__name__, str(recovery_exc)[:700],
                )
                return await _REMOTE_FALLBACK(target_crop, source_crop, log, trace=trace)

    # Weak/ambiguous source evidence: preserve the historical remote fallback.
    log("AI_SELFIE_V290B_IDENTITY trace=%s stage=local_gate_failed fallback=remote_stack reason=%s", trace, reason)
    return await _REMOTE_FALLBACK(target_crop, source_crop, log, trace=trace)


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
        _log("AI_SELFIE_V290B_SINGLEFLIGHT status=duplicate_callback_suppressed user_id=%s key=%s", user_id, key)
        return True
    if user_id and user_id in _ACTIVE_USERS:
        _SEEN[key] = now
        _log("AI_SELFIE_V290B_SINGLEFLIGHT status=concurrent_generation_suppressed user_id=%s key=%s", user_id, key)
        return True

    _SEEN[key] = now
    if user_id:
        _ACTIVE_USERS[user_id] = now
    _log("AI_SELFIE_V290B_SINGLEFLIGHT status=acquired user_id=%s key=%s", user_id, key)
    try:
        return bool(await _ORIGINAL_GENERATE(update, context, scene))
    finally:
        if user_id:
            _ACTIVE_USERS.pop(user_id, None)
        _log("AI_SELFIE_V290B_SINGLEFLIGHT status=released user_id=%s key=%s", user_id, key)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._prompt = _prompt
    terminal._identity_swap = _identity_swap
    terminal.generate = _generate_singleflight
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V290B"
    setattr(terminal, "_v290_camera_gaze", True)
    setattr(terminal, "_v290_hires_native_identity", True)
    setattr(terminal, "_v290_singleflight", True)
    setattr(terminal, "_v290b_local_first_recovery", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V290b local-first gaze + hires identity + singleflight installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
