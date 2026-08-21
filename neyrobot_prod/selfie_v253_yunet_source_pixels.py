# -*- coding: utf-8 -*-
"""V253: leave the low-resolution FaceSwap loop.

V252 proved two separate things in production:
1) removing the misaligned source-frequency repair removed most ghost/double edges;
2) the transferred PERSON-A face is still visibly softer than the untouched Gemini
   scene, even though the provider is fed a supersampled target and asked for PNG.

The reason is architectural: a FaceSwap model may synthesize/restore a small internal
face and then upscale it. Re-encoding that result as PNG or enlarging its target ROI
cannot recreate source pixels that never survived the swap model.

V253 therefore changes PERSON-A only:
- photo #3 remains the sole identity/expression authority;
- Gemini still creates the complete scene and PERSON-B exactly as before;
- OpenCV YuNet detects 5 facial landmarks on the real source and generated target;
- a similarity transform aligns the REAL source face to the generated target pose;
- source RGB pixels are colour-matched and feathered into PERSON-A only;
- no generative face restoration, FaceSwap or synthetic sharpening runs on success;
- the full result is encoded once as PNG and sent as an ORIGINAL Telegram document;
- delivery retries the original document instead of immediately degrading to photo;
- V252 Segmind V3 remains a safe fallback if YuNet/landmark transfer cannot run.

No new Telegram callback owner is registered. The stable V251 generation owner and
all payment/UX/scene/hero-isolation behavior remain authoritative.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
from pathlib import Path
from typing import Any

VERSION = "v253-yunet-source-pixel-lossless-2026-08-21"
_INSTALLED = False
_BASE_V252_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None
_BASE_DELIVER = None

_YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx"
)
_YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
_YUNET_PATH = Path("/tmp/neyrobot_models/face_detection_yunet_2023mar.onnx")
_YUNET_LOCK = asyncio.Lock()


def _modules():
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    from neyrobot_prod import selfie_v244_runtime_lock as v245
    from neyrobot_prod import selfie_v246_quality_hardlock as v246
    from neyrobot_prod import selfie_v247_provider_supersample as v247
    from neyrobot_prod import selfie_v248_faceswap_v4_quality as v249
    from neyrobot_prod import selfie_v250_hyperswap_identity as v250
    from neyrobot_prod import selfie_v251_v2_identity_detail as v251
    from neyrobot_prod import selfie_v252_v3_png_quality as v252
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v211_delivery as delivery
    return v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery


def _log(message: str, *args: Any) -> None:
    v241, *_ = _modules()
    v241._log(message, *args)


def _dims(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(bytes(data or b""))) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _ensure_yunet_model() -> Path:
    """Fetch the tiny official OpenCV YuNet model once and verify its checksum."""
    if _YUNET_PATH.exists():
        with contextlib.suppress(Exception):
            if _sha256_file(_YUNET_PATH) == _YUNET_SHA256:
                return _YUNET_PATH
        with contextlib.suppress(Exception):
            _YUNET_PATH.unlink()

    async with _YUNET_LOCK:
        if _YUNET_PATH.exists() and _sha256_file(_YUNET_PATH) == _YUNET_SHA256:
            return _YUNET_PATH

        v241, *_ = _modules()
        runtime = v241._runtime()
        httpx_mod = getattr(runtime, "httpx", None) if runtime is not None else None
        if httpx_mod is None:
            import httpx as httpx_mod

        _YUNET_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _YUNET_PATH.with_suffix(".download")
        timeout = httpx_mod.Timeout(60.0, connect=20.0, read=60.0, write=30.0, pool=20.0)
        async with httpx_mod.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(_YUNET_URL)
            response.raise_for_status()
            payload = bytes(response.content or b"")

        digest = hashlib.sha256(payload).hexdigest()
        if digest != _YUNET_SHA256:
            raise RuntimeError(f"YuNet checksum mismatch: {digest}")
        tmp.write_bytes(payload)
        tmp.replace(_YUNET_PATH)
        _log("AI_SELFIE_V253_YUNET status=downloaded bytes=%s sha256=%s", len(payload), digest[:16])
        return _YUNET_PATH


def _decode_bgr(data: bytes):
    import cv2
    import numpy as np

    buf = np.frombuffer(bytes(data or b""), dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("OpenCV could not decode image")
    return frame


def _yunet_face(frame, model_path: Path, *, label: str):
    """Return bbox + five landmarks in original frame coordinates."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    if w < 96 or h < 96:
        raise RuntimeError(f"{label} image too small for landmarks")

    max_side = float(max(w, h))
    trial_sides = (640.0, 512.0, 448.0, 384.0)
    seen: set[tuple[int, int]] = set()
    best = None

    for side in trial_sides:
        scale = min(1.0, side / max_side)
        rw = max(96, int(round(w * scale)))
        rh = max(96, int(round(h * scale)))
        if (rw, rh) in seen:
            continue
        seen.add((rw, rh))
        small = frame if (rw, rh) == (w, h) else cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_AREA)
        detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (rw, rh), score_threshold=0.62, nms_threshold=0.30, top_k=1000
        )
        _, faces = detector.detect(small)
        if faces is None or len(faces) == 0:
            continue

        row = max(faces, key=lambda r: float(r[2]) * float(r[3]))
        score = float(row[14]) if len(row) > 14 else 0.0
        inv = 1.0 / max(scale, 1e-8)
        bbox = np.asarray(row[0:4], dtype=np.float32) * inv
        landmarks = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2) * inv
        area = float(bbox[2] * bbox[3])
        candidate = (area, score, bbox, landmarks)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate

    if best is None:
        raise RuntimeError(f"YuNet found no face in {label}")

    _, score, bbox, landmarks = best
    x, y, fw, fh = [float(v) for v in bbox]
    if fw < 80 or fh < 80:
        raise RuntimeError(f"YuNet {label} face too small: {fw:.0f}x{fh:.0f}")
    _log(
        "AI_SELFIE_V253_LANDMARKS label=%s frame=%sx%s face=%.0f,%.0f,%.0f,%.0f score=%.3f",
        label, w, h, x, y, fw, fh, score,
    )
    return bbox, landmarks


def _colour_match_lab(warped, target, mask):
    """Match broad target lighting without destroying source high-frequency detail."""
    import cv2
    import numpy as np

    region = mask > 80
    if int(region.sum()) < 500:
        return warped

    src_lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
    tgt_lab = cv2.cvtColor(target, cv2.COLOR_BGR2LAB).astype(np.float32)
    out = src_lab.copy()

    for channel in range(3):
        s = src_lab[:, :, channel][region]
        t = tgt_lab[:, :, channel][region]
        sm, tm = float(s.mean()), float(t.mean())
        ss, ts = float(s.std()), float(t.std())
        gain = 1.0 if ss < 1.0 else max(0.78, min(1.22, ts / ss))
        adjusted = (src_lab[:, :, channel] - sm) * gain + tm
        out[:, :, channel] = np.clip(adjusted, 0.0, 255.0)

    return cv2.cvtColor(out.astype(np.uint8), cv2.COLOR_LAB2BGR)


def _source_pixel_transfer(stage1: bytes, source: bytes, model_path: Path) -> bytes:
    """Similarity-align real photo #3 pixels into PERSON-A; PERSON-B is untouched."""
    import cv2
    import numpy as np

    target = _decode_bgr(stage1)
    source_im = _decode_bgr(source)
    th, tw = target.shape[:2]
    sh, sw = source_im.shape[:2]

    # Hard PERSON-B firewall: landmarks are detected only in the left 55% of stage1.
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    left = target[:, :firewall_x].copy()
    source_bbox, source_pts = _yunet_face(source_im, model_path, label="source_photo3")
    target_bbox_local, target_pts = _yunet_face(left, model_path, label="target_person_a")
    target_bbox = target_bbox_local.copy()

    # Estimate a similarity transform (rotation + uniform scale + translation).
    matrix, inliers = cv2.estimateAffinePartial2D(
        source_pts.astype(np.float32),
        target_pts.astype(np.float32),
        method=cv2.LMEDS,
    )
    if matrix is None:
        raise RuntimeError("YuNet landmarks could not estimate similarity transform")

    a, b = float(matrix[0, 0]), float(matrix[0, 1])
    scale = max(1e-8, (a * a + b * b) ** 0.5)
    sx, sy, sfw, sfh = [float(v) for v in source_bbox]
    tx, ty, tfw, tfh = [float(v) for v in target_bbox]
    if scale > 1.45:
        raise RuntimeError(f"source face would need excessive enlargement: scale={scale:.3f}")
    if scale < 0.20:
        raise RuntimeError(f"invalid face scale: {scale:.3f}")

    warped = cv2.warpAffine(
        source_im,
        matrix,
        (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    # Source-face oval: real eyes/nose/mouth/cheeks/jaw, but target hair/ears/body.
    source_mask = np.zeros((sh, sw), dtype=np.uint8)
    center = (int(round(sx + sfw * 0.50)), int(round(sy + sfh * 0.56)))
    axes = (max(12, int(round(sfw * 0.45))), max(12, int(round(sfh * 0.48))))
    cv2.ellipse(source_mask, center, axes, 0.0, 0.0, 360.0, 255, thickness=-1, lineType=cv2.LINE_AA)
    warped_mask = cv2.warpAffine(
        source_mask,
        matrix,
        (tw, th),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    # Enforce left-person firewall even if an affine edge extends too far.
    warped_mask[:, firewall_x:] = 0
    feather = max(7, min(24, int(round(min(tfw, tfh) * 0.035))))
    warped_mask = cv2.GaussianBlur(warped_mask, (0, 0), sigmaX=float(feather), sigmaY=float(feather))
    matched = _colour_match_lab(warped, target, warped_mask)

    alpha = (warped_mask.astype(np.float32) / 255.0)[:, :, None]
    final = np.clip(matched.astype(np.float32) * alpha + target.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())
    _log(
        "AI_SELFIE_V253_TRANSFER status=success method=yunet_similarity_source_pixels source=%sx%s target=%sx%s source_face=%.0fx%.0f target_face=%.0fx%.0f scale=%.3f feather=%s hero_firewall_x=%s output=png bytes=%s source_pixels=true synthetic_face=false",
        sw, sh, tw, th, sfw, sfh, tfw, tfh, scale, feather, firewall_x, len(output),
    )
    return output


async def _true_face_transfer_v253(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    """Prefer real aligned source pixels; use frozen V252 only as failure fallback."""
    global _BASE_TRUE_FACE_TRANSFER
    try:
        if int(source_photo_no) != 3:
            raise RuntimeError(f"V253 requires authoritative photo #3, got #{source_photo_no}")
        model_path = await _ensure_yunet_model()
        final = _source_pixel_transfer(bytes(stage1 or b""), bytes(source or b""), model_path)
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_source_pixels_v253"
        return final, "opencv_yunet_similarity_real_source_pixels"
    except Exception as exc:
        _log(
            "AI_SELFIE_V253_TRANSFER status=fallback_v252 reason=%s:%s",
            type(exc).__name__, str(exc)[:300],
        )
        if not callable(_BASE_TRUE_FACE_TRANSFER):
            raise
        return await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)


def _document_name(raw: bytes) -> str:
    return "celebrity_selfie.png" if bytes(raw or b"").startswith(b"\x89PNG\r\n\x1a\n") else "celebrity_selfie.jpg"


async def _send_original_document(message: Any, raw: bytes, caption: str, *, timeout: float) -> None:
    from telegram import InputFile

    bio = io.BytesIO(bytes(raw or b""))
    bio.name = _document_name(raw)
    await message.reply_document(
        document=InputFile(bio, filename=bio.name),
        caption=caption,
        write_timeout=timeout,
        read_timeout=timeout,
        connect_timeout=60.0,
        pool_timeout=60.0,
    )


async def _deliver_original(message: Any, raw: bytes, caption: str, *, prefer_document: bool) -> bytes:
    """Do not shrink a 2K result before document upload; retry network failures."""
    global _BASE_DELIVER
    data = bytes(raw or b"")
    if not prefer_document:
        if callable(_BASE_DELIVER):
            return await _BASE_DELIVER(message, data, caption, prefer_document=False)
        raise RuntimeError("V253 base delivery unavailable")

    w, h = _dims(data)
    _log(
        "AI_SELFIE_V253_DELIVERY_START mode=original_document dims=%sx%s bytes=%s filename=%s downscale=false recompress=false",
        w, h, len(data), _document_name(data),
    )

    errors: list[str] = []
    for attempt, timeout in enumerate((300.0, 360.0, 420.0), 1):
        try:
            await _send_original_document(message, data, caption, timeout=timeout)
            _log(
                "AI_SELFIE_V253_DELIVERY_SUCCESS attempt=%s mode=document original=true dims=%sx%s bytes=%s telegram_photo_compression=false",
                attempt, w, h, len(data),
            )
            return data
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            _log(
                "AI_SELFIE_V253_DELIVERY_RETRY attempt=%s reason=%s:%s original_retained=true",
                attempt, type(exc).__name__, str(exc)[:220],
            )
            if attempt < 3:
                await asyncio.sleep(float(attempt * 3))

    # Last-resort preview only. It is explicitly logged as compressed and is not
    # allowed to masquerade as the original 2K file.
    _, _, _, _, _, _, _, _, _, _, _, delivery = _modules()
    preview = delivery._jpeg(data, max_side=1800, quality=91)
    try:
        await delivery._send_photo(
            message,
            preview,
            caption + "\n⚠️ Telegram не принял оригинал как документ; отправлена сжатая превью-копия.",
            timeout=300.0,
        )
        _log(
            "AI_SELFIE_V253_DELIVERY_FALLBACK mode=photo_preview original=false bytes=%s errors=%s",
            len(preview), " | ".join(errors)[-600:],
        )
        return preview
    except Exception as exc:
        raise RuntimeError("V253 original delivery failed: " + " | ".join(errors + [f"preview: {type(exc).__name__}: {exc}"]))


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V252, then own only PERSON-A transfer and lossless delivery."""
    global _BASE_V252_ENFORCE
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()
    if not callable(_BASE_V252_ENFORCE):
        raise RuntimeError("V253 base V252 enforcer was not captured")

    _BASE_V252_ENFORCE(bind_generate=bind_generate)
    transfer._true_face_transfer = _true_face_transfer_v253
    delivery._deliver = _deliver_original

    # Reuse the existing V251 callback owner; only redirect late enforcers here.
    v252.enforce_runtime = enforce_runtime
    v251.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, delivery, v241, v245, v246, v247, v249, v250, v251, v252):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v253-front-camera-yunet-real-source-pixels-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 scene/expression -> YuNet 5-landmark similarity alignment -> "
            "real photo-3 face pixels with LAB lighting match + feathered PERSON-A-only blend -> "
            "native PNG -> original Telegram document; V252 Segmind V3 fallback only"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V253_ENFORCE status=ok base=v252 primary=opencv_yunet_source_pixels landmarks=5 transform=similarity colour=lab blend=feathered source_pixels=true faceswap_primary=false fallback=v252 delivery=original_document_retry hero=pixel_locked version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V252_ENFORCE, _BASE_TRUE_FACE_TRANSFER, _BASE_DELIVER
    v241, _, _, _, _, _, _, v252, transfer, _, _, delivery = _modules()
    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v252.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V252_ENFORCE = current

    # Freeze the complete V252 path before overriding it; this is the safe fallback.
    current(bind_generate=True)
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer
    _BASE_DELIVER = delivery._deliver

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V253 YuNet real source-pixel + original-document owner installed", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
