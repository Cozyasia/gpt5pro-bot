# -*- coding: utf-8 -*-
"""V292 source-authoritative identity, iris-only camera gaze and face-safe integration.

Fixes visible after V291:
- PERSON A could still look partly Gemini-generated because the source face was
  anisotropically warped to the generated target geometry;
- restoring whole target eye patches weakened identity;
- the old full-resolution integration ellipse was wide enough to touch PERSON B
  in tight two-person selfies, producing a visible/pixelated edge near the hero;
- repeated JPEG round-trips softened the transferred face.

V292 keeps the memory-safe V291 design but makes photo #3 authoritative for the
user's facial geometry and texture. The source face is mapped with a similarity
(uniform-scale) transform, intermediate identity stages stay lossless PNG, only a
small iris region may be borrowed from the generated target for camera gaze, and
final reintegration is constrained to PERSON A's face-safe ROI.
"""
from __future__ import annotations

import contextlib
import gc
import math
import time
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v289_native_identity_primary as v289

VERSION = "v292-source-authoritative-face-safe-2026-08-17"
_INSTALLED = False
_ORIGINAL_PROMPT = terminal._prompt
_ORIGINAL_GENERATE = terminal.generate
_ORIGINAL_EDGE_COMPOSITE = terminal._edge_composite_fullres
_REMOTE_FALLBACK = v289._ORIGINAL_IDENTITY_SWAP

_SEEN: dict[str, float] = {}
_ACTIVE_USERS: dict[int, float] = {}
_TTL = 20.0 * 60.0


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _png(img: Any) -> bytes:
    out = BytesIO()
    img.save(out, "PNG", optimize=False, compress_level=2)
    return out.getvalue()


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    text = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    label = str(shot_label or "").lower()
    if "селфи" in label or "selfie" in label:
        text += (
            " CAMERA-GAZE CONTRACT: both principal people look naturally into the front-camera lens. "
            "PERSON A in this composition is ONLY a temporary pose/body placeholder: do not treat the generated face as identity. "
            "Leave PERSON A near-frontal, unobstructed and large enough for later deterministic identity transfer. "
            "No hair, hands, glasses, hero shoulder, props or shadows may cross PERSON A's eyes, nose, mouth, jaw or cheek boundary."
        )
    else:
        text += (
            " PERSON A FACE TRANSFER CONTRACT: PERSON A's generated face is temporary geometry only. "
            "Keep it unobstructed, near-frontal and separated from PERSON B so the later source-photo identity transfer has a clean boundary."
        )
    return text


def _source_authoritative_core(source_crop: bytes, target_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, dict[str, Any]]:
    """Transfer source facial geometry with uniform scale, not target-face morphing."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    src = fs.image(source_crop).convert("RGB")
    dst = fs.image(target_crop).convert("RGB")
    warped = mask = soft = merged = None
    try:
        source_face = fs.source_face_crop(source_crop, None)
        target_face = fs.source_face_crop(target_crop, None)
        sx, sy, sw, sh = [float(v) for v in source_face.face_box]
        tx, ty, tw, th = [float(v) for v in target_face.face_box]
        if sw < 300 or sh < 300:
            raise ValueError(f"source portrait face too small for authoritative core: {int(sw)}x{int(sh)}")
        if tw < 170 or th < 170:
            raise ValueError(f"target face too small for authoritative core: {int(tw)}x{int(th)}")

        # Similarity mapping: preserve the user's own facial aspect ratio/proportions.
        # Geometric mean is less biased than width-only or height-only fitting.
        map_scale = math.sqrt(max(0.01, (sw / max(tw, 1.0)) * (sh / max(th, 1.0))))
        source_cx = sx + sw * 0.5
        source_cy = sy + sh * 0.50
        target_cx = tx + tw * 0.5
        target_cy = ty + th * 0.50

        # Face-only patch. It includes jaw/cheeks/forehead but deliberately excludes
        # most hair and shoulders, preventing the PERSON-B boundary contamination.
        left = max(0, int(round(tx - tw * 0.16)))
        top = max(0, int(round(ty - th * 0.17)))
        right = min(dst.width, int(round(tx + tw * 1.16)))
        bottom = min(dst.height, int(round(ty + th * 1.15)))
        pw, ph = right - left, bottom - top
        if pw < 100 or ph < 100:
            raise ValueError("authoritative face patch too small")

        # PIL affine is output -> source. Keep one uniform scale on both axes.
        c = source_cx + (float(left) - target_cx) * map_scale
        f = source_cy + (float(top) - target_cy) * map_scale
        affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        warped = src.transform((pw, ph), affine, (map_scale, 0.0, c, 0.0, map_scale, f), resample=resample, fillcolor=(0, 0, 0))
        warped = ImageEnhance.Sharpness(warped).enhance(1.06)

        # Soft outer transition, large fully source-owned interior. This keeps real
        # source pixels through eyes/nose/mouth/cheeks instead of a generated morph.
        mask = Image.new("L", (pw, ph), 0)
        draw = ImageDraw.Draw(mask)
        mx = max(5, int(round(pw * 0.075)))
        my_top = max(4, int(round(ph * 0.055)))
        my_bottom = max(7, int(round(ph * 0.085)))
        draw.ellipse((mx, my_top, pw - mx, ph - my_bottom), fill=255)
        blur = max(2.0, min(pw, ph) * 0.022)
        soft = mask.filter(ImageFilter.GaussianBlur(blur))

        ref = dst.crop((left, top, right, bottom))
        try:
            merged = Image.composite(warped, ref, soft)
            out_img = dst.copy()
            try:
                out_img.paste(merged, (left, top))
                payload = _png(out_img)
            finally:
                out_img.close()
        finally:
            ref.close()

        meta = {
            "mode": "v292_source_authoritative_similarity_core",
            "source_face_px": (int(sw), int(sh)),
            "target_face_px": (int(tw), int(th)),
            "patch": (left, top, right, bottom),
            "uniform_map_scale": round(map_scale, 5),
            "intermediate": "png_lossless",
        }
        log(
            "AI_SELFIE_V292_IDENTITY trace=%s stage=source_authoritative_core source_face=%sx%s target_face=%sx%s patch=%s scale=%.5f out=%s format=png",
            trace, int(sw), int(sh), int(tw), int(th), meta["patch"], map_scale, fs.dims(payload),
        )
        return payload, meta
    finally:
        for obj in (merged, soft, mask, warped, src, dst):
            with contextlib.suppress(Exception):
                if obj is not None:
                    obj.close()


def _iris_only_camera_gaze(target_raw: bytes, identity_raw: bytes, log: Any, *, trace: str) -> bytes:
    """Preserve source eyelids/eye shape; borrow only tiny target iris/sclera centers."""
    from PIL import Image, ImageDraw, ImageFilter

    target = fs.image(target_raw).convert("RGB")
    identity = fs.image(identity_raw).convert("RGB")
    mask = soft = merged = None
    try:
        if identity.size != target.size:
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized = identity.resize(target.size, resample)
            identity.close()
            identity = resized
        try:
            face = fs.source_face_crop(identity_raw, None)
            fx, fy, fw, fh = [float(v) for v in face.face_box]
        except Exception:
            face = fs.source_face_crop(target_raw, None)
            fx, fy, fw, fh = [float(v) for v in face.face_box]

        # Intentionally much smaller than V291: do not replace eyelids/brows or the
        # user's characteristic eye shape. These masks mainly cover iris+sclera center.
        centers = [(fx + fw * 0.315, fy + fh * 0.405), (fx + fw * 0.685, fy + fh * 0.405)]
        eye_w = max(10.0, fw * 0.105)
        eye_h = max(7.0, fh * 0.052)
        mask = Image.new("L", target.size, 0)
        draw = ImageDraw.Draw(mask)
        for cx, cy in centers:
            draw.ellipse((cx - eye_w / 2, cy - eye_h / 2, cx + eye_w / 2, cy + eye_h / 2), fill=165)
        soft = mask.filter(ImageFilter.GaussianBlur(max(1.0, fw * 0.006)))
        merged = Image.composite(target, identity, soft)
        payload = _png(merged)
        log("AI_SELFIE_V292_GAZE trace=%s status=iris_only face=%s out=%s", trace, face.face_box, fs.dims(payload))
        return payload
    except Exception as exc:
        log("AI_SELFIE_V292_GAZE trace=%s status=skip error_type=%s error=%s", trace, type(exc).__name__, str(exc)[:350])
        return identity_raw
    finally:
        for obj in (merged, soft, mask, target, identity):
            with contextlib.suppress(Exception):
                if obj is not None:
                    obj.close()


def _edge_composite_face_safe(base_img: Any, target: Any, swapped_crop_raw: bytes) -> bytes:
    """Integrate PERSON A only; never feather over the adjacent hero."""
    from PIL import Image, ImageDraw, ImageFilter

    cl, ct, cr, cb = target.crop_box
    cw, ch = cr - cl, cb - ct
    provider = fs.image(swapped_crop_raw).convert("RGB")
    original_crop = None
    provider_region = original_region = mask = soft = merged_region = merged_crop = output = None
    try:
        if provider.size != (cw, ch):
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized = provider.resize((cw, ch), resample)
            provider.close()
            provider = resized

        original_crop = base_img.crop(target.crop_box)
        fx, fy, fw, fh = [int(v) for v in target.face_box]
        local_face = (fx - cl, fy - ct, fw, fh)
        # V257 used 1.82 x 2.04. That can cover the neighbouring face in a close
        # two-person selfie. V292 confines replacement to PERSON A face/head interior.
        region = fs._expand(local_face, (cw, ch), 1.46, 1.62, 0.000)
        left, top, right, bottom = region
        rw, rh = right - left, bottom - top
        provider_region = provider.crop(region)
        original_region = original_crop.crop(region)

        mask = Image.new("L", (rw, rh), 0)
        draw = ImageDraw.Draw(mask)
        mx = max(5, int(round(rw * 0.075)))
        my = max(5, int(round(rh * 0.065)))
        draw.ellipse((mx, my, rw - mx, rh - my), fill=255)
        # Wider feather eliminates hard/pixelated border; outside the face-safe ROI
        # PERSON B stays byte-for-byte from the Gemini composition.
        soft = mask.filter(ImageFilter.GaussianBlur(max(3.0, min(rw, rh) * 0.030)))
        merged_region = Image.composite(provider_region, original_region, soft)
        merged_crop = original_crop.copy()
        merged_crop.paste(merged_region, (left, top))
        output = base_img.copy()
        output.paste(merged_crop, (cl, ct))
        payload = fs.jpeg(output, max_side=2560, quality=100)
        _log(
            "AI_SELFIE_V292_INTEGRATION status=face_safe target_crop=%s face=%s region=%s provider=%s out=%s hero_protection=true",
            target.crop_box, target.face_box, region, fs.dims(swapped_crop_raw), fs.dims(payload),
        )
        return payload
    finally:
        for obj in (output, merged_crop, merged_region, soft, mask, original_region, provider_region, original_crop, provider):
            with contextlib.suppress(Exception):
                if obj is not None:
                    obj.close()


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    safe, reason = v289._local_gate(target_crop, source_crop, log, trace=trace)
    if safe:
        try:
            candidate, meta = _source_authoritative_core(source_crop, target_crop, log, trace=trace)
            if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
                raise RuntimeError("V292 authoritative core returned unchanged/empty target")
            geometry_ok, geometry_reason = v289._geometry_status(target_crop, candidate, log, trace=trace)
            if not geometry_ok:
                raise RuntimeError(f"V292 geometry rejected: {geometry_reason}")
            candidate = _iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
            log(
                "AI_SELFIE_V292_IDENTITY trace=%s stage=authoritative_success mode=%s target=%s source=%s out=%s remote_provider=false source_photo3=true anisotropic_warp=false jpeg_roundtrips=0",
                trace, meta.get("mode"), fs.dims(target_crop), fs.dims(source_crop), fs.dims(candidate),
            )
            return candidate, "source_photo3_authoritative_v292_similarity_core"
        except Exception as exc:
            log(
                "AI_SELFIE_V292_IDENTITY trace=%s stage=authoritative_failed error_type=%s error=%s fallback=v289b",
                trace, type(exc).__name__, str(exc)[:700],
            )

        # Proven local/remote stack remains a fallback, not the default identity owner.
        try:
            candidate, provider = await v289._identity_swap(target_crop, source_crop, log, trace=trace)
            if len(candidate) >= 1024 and fs.sha(candidate) != fs.sha(target_crop):
                candidate = _iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
                log("AI_SELFIE_V292_IDENTITY trace=%s stage=v289_recovery_success provider=%s out=%s", trace, provider, fs.dims(candidate))
                return candidate, provider + "+v292_iris_gaze"
        except Exception as recovery_exc:
            log("AI_SELFIE_V292_IDENTITY trace=%s stage=v289_recovery_failed error_type=%s error=%s", trace, type(recovery_exc).__name__, str(recovery_exc)[:700])

    log("AI_SELFIE_V292_IDENTITY trace=%s stage=remote_last_resort reason=%s", trace, reason)
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
        _log("AI_SELFIE_V292_SINGLEFLIGHT status=duplicate_callback_suppressed user_id=%s key=%s", user_id, key)
        return True
    if user_id and user_id in _ACTIVE_USERS:
        _SEEN[key] = now
        _log("AI_SELFIE_V292_SINGLEFLIGHT status=concurrent_generation_suppressed user_id=%s key=%s", user_id, key)
        return True
    _SEEN[key] = now
    if user_id:
        _ACTIVE_USERS[user_id] = now
    _log("AI_SELFIE_V292_SINGLEFLIGHT status=acquired user_id=%s key=%s", user_id, key)
    try:
        return bool(await _ORIGINAL_GENERATE(update, context, scene))
    finally:
        if user_id:
            _ACTIVE_USERS.pop(user_id, None)
        gc.collect()
        _log("AI_SELFIE_V292_SINGLEFLIGHT status=released user_id=%s key=%s", user_id, key)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._prompt = _prompt
    terminal._identity_swap = _identity_swap
    terminal._edge_composite_fullres = _edge_composite_face_safe
    terminal.generate = _generate_singleflight
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V292"
    setattr(terminal, "_v292_source_authoritative", True)
    setattr(terminal, "_v292_face_safe_integration", True)
    setattr(terminal, "_v292_iris_only_gaze", True)
    setattr(terminal, "_v292_singleflight", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V292 source-authoritative identity + face-safe integration installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
