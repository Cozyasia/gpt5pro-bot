# -*- coding: utf-8 -*-
"""V295 source-photo identity fidelity lock.

V294 removed the Stage-1 stall. The first post-V294 production trace exposed a
separate identity bug: V292's source-authoritative affine path requested LANCZOS
from PIL.Image.transform(), but affine transforms only accept NEAREST/BILINEAR/
BICUBIC. That exception forced every otherwise-good source into the Replicate
fallback, which produced a plausible look-alike rather than photo-3 geometry.

V295 fixes the affine resampler, expands the source-owned facial interior to keep
jaw/cheek/forehead/hairline proportions, uses only a very small iris correction,
and re-locks photo #3 after any remote fallback before final integration.
"""
from __future__ import annotations

import contextlib
import math
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v289_native_identity_primary as v289
from neyrobot_prod import selfie_v290_gaze_quality_singleflight as v292

VERSION = "v295-source-photo3-likeness-lock-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _png(img: Any) -> bytes:
    out = BytesIO()
    img.save(out, "PNG", optimize=False, compress_level=2)
    return out.getvalue()


def _source_authoritative_core(source_crop: bytes, target_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, dict[str, Any]]:
    """Map photo #3 with uniform geometry and a PIL-supported affine resampler."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    src = fs.image(source_crop).convert("RGB")
    dst = fs.image(target_crop).convert("RGB")
    warped = mask = soft = merged = None
    try:
        source_face = fs.source_face_crop(source_crop, None)
        target_face = fs.source_face_crop(target_crop, None)
        sx, sy, sw, sh = [float(v) for v in source_face.face_box]
        tx, ty, tw, th = [float(v) for v in target_face.face_box]
        if sw < 260 or sh < 260:
            raise ValueError(f"V295 source face too small: {int(sw)}x{int(sh)}")
        if tw < 150 or th < 150:
            raise ValueError(f"V295 target face too small: {int(tw)}x{int(th)}")

        # Inverse affine scale (output -> source), uniform on X/Y. This preserves
        # the user's own width/height relation rather than morphing to Gemini's face.
        map_scale = math.sqrt(max(0.01, (sw / max(tw, 1.0)) * (sh / max(th, 1.0))))
        source_cx = sx + sw * 0.5
        source_cy = sy + sh * 0.50
        target_cx = tx + tw * 0.5
        target_cy = ty + th * 0.50

        # Own more of the real face than V292: brows, forehead/hairline, cheeks and
        # jaw are identity-bearing. Still stop well before the neighbouring hero.
        left = max(0, int(round(tx - tw * 0.22)))
        top = max(0, int(round(ty - th * 0.30)))
        right = min(dst.width, int(round(tx + tw * 1.22)))
        bottom = min(dst.height, int(round(ty + th * 1.22)))
        pw, ph = right - left, bottom - top
        if pw < 120 or ph < 120:
            raise ValueError("V295 authoritative patch too small")

        c = source_cx + (float(left) - target_cx) * map_scale
        f = source_cy + (float(top) - target_cy) * map_scale
        affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
        # Critical V295 fix: Image.transform(AFFINE) does NOT support LANCZOS.
        resample = Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC
        warped = src.transform(
            (pw, ph), affine,
            (map_scale, 0.0, c, 0.0, map_scale, f),
            resample=resample,
            fillcolor=(0, 0, 0),
        )
        warped = ImageEnhance.Sharpness(warped).enhance(1.10)

        mask = Image.new("L", (pw, ph), 0)
        draw = ImageDraw.Draw(mask)
        mx = max(4, int(round(pw * 0.045)))
        my_top = max(3, int(round(ph * 0.035)))
        my_bottom = max(5, int(round(ph * 0.055)))
        draw.ellipse((mx, my_top, pw - mx, ph - my_bottom), fill=255)
        # Narrower feather means eyes/nose/mouth/jaw remain source-owned; only the
        # outer skin transition is blended into scene lighting.
        blur = max(1.8, min(pw, ph) * 0.015)
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
            "mode": "v295_source_photo3_similarity_lock",
            "source_face_px": (int(sw), int(sh)),
            "target_face_px": (int(tw), int(th)),
            "patch": (left, top, right, bottom),
            "uniform_map_scale": round(map_scale, 5),
            "resampler": "bicubic",
            "source_owned": "eyes+nose+mouth+cheeks+jaw+forehead+hairline",
        }
        log(
            "AI_SELFIE_V295_IDENTITY trace=%s stage=source_lock source_face=%sx%s target_face=%sx%s patch=%s scale=%.5f resample=bicubic out=%s",
            trace, int(sw), int(sh), int(tw), int(th), meta["patch"], map_scale, fs.dims(payload),
        )
        return payload, meta
    finally:
        for obj in (merged, soft, mask, warped, src, dst):
            with contextlib.suppress(Exception):
                if obj is not None:
                    obj.close()


def _iris_only_camera_gaze(target_raw: bytes, identity_raw: bytes, log: Any, *, trace: str) -> bytes:
    """Tiny lens-gaze correction without replacing the user's eyelids or eye shape."""
    from PIL import Image, ImageDraw, ImageFilter

    target = fs.image(target_raw).convert("RGB")
    identity = fs.image(identity_raw).convert("RGB")
    mask = soft = merged = None
    try:
        if identity.size != target.size:
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            resized = identity.resize(target.size, resample)
            identity.close(); identity = resized
        try:
            face = fs.source_face_crop(identity_raw, None)
        except Exception:
            face = fs.source_face_crop(target_raw, None)
        fx, fy, fw, fh = [float(v) for v in face.face_box]
        centers = [(fx + fw * 0.315, fy + fh * 0.405), (fx + fw * 0.685, fy + fh * 0.405)]
        eye_w = max(8.0, fw * 0.082)
        eye_h = max(6.0, fh * 0.040)
        mask = Image.new("L", target.size, 0)
        draw = ImageDraw.Draw(mask)
        for cx, cy in centers:
            draw.ellipse((cx-eye_w/2, cy-eye_h/2, cx+eye_w/2, cy+eye_h/2), fill=105)
        soft = mask.filter(ImageFilter.GaussianBlur(max(0.9, fw * 0.0045)))
        merged = Image.composite(target, identity, soft)
        payload = _png(merged)
        log("AI_SELFIE_V295_GAZE trace=%s status=iris_micro face=%s strength=105 out=%s", trace, face.face_box, fs.dims(payload))
        return payload
    except Exception as exc:
        log("AI_SELFIE_V295_GAZE trace=%s status=skip error_type=%s error=%s", trace, type(exc).__name__, str(exc)[:350])
        return identity_raw
    finally:
        for obj in (merged, soft, mask, target, identity):
            with contextlib.suppress(Exception):
                if obj is not None:
                    obj.close()


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    safe, reason = v289._local_gate(target_crop, source_crop, log, trace=trace)
    if safe:
        try:
            candidate, meta = _source_authoritative_core(source_crop, target_crop, log, trace=trace)
            if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
                raise RuntimeError("V295 source lock returned unchanged/empty target")
            geometry_ok, geometry_reason = v289._geometry_status(target_crop, candidate, log, trace=trace)
            if not geometry_ok:
                raise RuntimeError(f"V295 geometry rejected: {geometry_reason}")
            candidate = _iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
            log("AI_SELFIE_V295_IDENTITY trace=%s stage=authoritative_success source_photo3=true remote=false out=%s", trace, fs.dims(candidate))
            return candidate, "source_photo3_authoritative_v295"
        except Exception as exc:
            log("AI_SELFIE_V295_IDENTITY trace=%s stage=authoritative_failed error_type=%s error=%s fallback=v289", trace, type(exc).__name__, str(exc)[:700])

        # Remote providers can establish pose/lighting, but they are never allowed to
        # be the final identity owner. Re-lock photo #3 over their result.
        try:
            remote, provider = await v289._identity_swap(target_crop, source_crop, log, trace=trace)
            if len(remote) >= 1024 and fs.sha(remote) != fs.sha(target_crop):
                try:
                    relocked, _ = _source_authoritative_core(source_crop, remote, log, trace=trace)
                    relocked = _iris_only_camera_gaze(target_crop, relocked, log, trace=trace)
                    log("AI_SELFIE_V295_IDENTITY trace=%s stage=remote_relocked provider=%s out=%s source_photo3_final_owner=true", trace, provider, fs.dims(relocked))
                    return relocked, provider + "+v295_source_relock"
                except Exception as relock_exc:
                    log("AI_SELFIE_V295_IDENTITY trace=%s stage=remote_relock_failed provider=%s error_type=%s error=%s", trace, provider, type(relock_exc).__name__, str(relock_exc)[:600])
                remote = _iris_only_camera_gaze(target_crop, remote, log, trace=trace)
                return remote, provider + "+v295_iris_only"
        except Exception as recovery_exc:
            log("AI_SELFIE_V295_IDENTITY trace=%s stage=v289_failed error_type=%s error=%s", trace, type(recovery_exc).__name__, str(recovery_exc)[:700])

    log("AI_SELFIE_V295_IDENTITY trace=%s stage=remote_last_resort reason=%s", trace, reason)
    remote, provider = await v292._REMOTE_FALLBACK(target_crop, source_crop, log, trace=trace)
    # Best-effort source re-lock even on last-resort provider output.
    try:
        relocked, _ = _source_authoritative_core(source_crop, remote, log, trace=trace)
        relocked = _iris_only_camera_gaze(target_crop, relocked, log, trace=trace)
        return relocked, str(provider) + "+v295_source_relock"
    except Exception:
        return remote, provider


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    # V292's identity function resolves these globals dynamically, but install our
    # terminal identity owner explicitly so later overlays cannot silently retain the
    # old LANCZOS-affine fallback behavior.
    v292._source_authoritative_core = _source_authoritative_core
    v292._iris_only_camera_gaze = _iris_only_camera_gaze
    v292._identity_swap = _identity_swap
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V295"
    setattr(terminal, "_v295_source_photo3_likeness_lock", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V295 source-photo3 likeness lock installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]