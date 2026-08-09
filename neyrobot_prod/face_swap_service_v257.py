# -*- coding: utf-8 -*-
"""V257 shared production Face Swap service.

Goals:
- photo #3 is the sole identity source;
- a single PiAPI/Qubico face-swap call is authoritative by default;
- PERSON A target acquisition is strict and never falls back to a random wall/background box;
- no Gemini call is allowed after PiAPI;
- only the outer boundary of the provider result is feathered into the untouched scene.

This module intentionally does not monkey-patch legacy V239-V256 modules.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx

VERSION = "v257-consolidated-faceswap-service-2026-08-09"
PIAPI_TASK_URL = "https://api.piapi.ai/api/v1/task"


@dataclass(frozen=True)
class FaceTarget:
    face_box: tuple[int, int, int, int]
    crop_box: tuple[int, int, int, int]
    crop_raw: bytes
    support: int
    eye_count: int
    score: float


def sha(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw or b"")).hexdigest()[:12]


def image(raw: bytes) -> Any:
    from PIL import Image, ImageOps
    return ImageOps.exif_transpose(Image.open(BytesIO(bytes(raw or b"")))).convert("RGB")


def jpeg(img: Any, *, max_side: int = 1900, quality: int = 96) -> bytes:
    from PIL import Image
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue()


def dims(raw: bytes) -> str:
    try:
        w, h = image(raw).size
        return f"{w}x{h}"
    except Exception:
        return "invalid"


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return float(inter) / float(union) if union else 0.0


def _expand(box: tuple[int, int, int, int], size: tuple[int, int], wf: float, hf: float, ys: float = 0.0) -> tuple[int, int, int, int]:
    x, y, w, h = box
    iw, ih = size
    cx = x + w / 2.0
    cy = y + h / 2.0 + h * ys
    cw = max(160.0, w * wf)
    ch = max(190.0, h * hf)
    left = max(0, int(round(cx - cw / 2.0)))
    top = max(0, int(round(cy - ch / 2.0)))
    right = min(iw, int(round(cx + cw / 2.0)))
    bottom = min(ih, int(round(cy + ch / 2.0)))
    if right - left < 128 or bottom - top < 128:
        raise ValueError("face crop is too small")
    return left, top, right, bottom


def _detect_clusters(img: Any, *, roi: tuple[int, int, int, int] | None = None) -> list[dict[str, Any]]:
    """Multi-cascade face detection with agreement/eye evidence.

    Returns clustered boxes in full-image coordinates. A single weak Haar hit is not
    enough for a production target unless eye evidence is present.
    """
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    iw, ih = img.size
    if roi is None:
        rx1, ry1, rx2, ry2 = 0, 0, iw, ih
    else:
        rx1, ry1, rx2, ry2 = roi
    crop = img.crop((rx1, ry1, rx2, ry2))
    rgb = np.asarray(crop)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    equalized = cv2.equalizeHist(gray)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    cascades = [
        cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"),
        cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"),
    ]
    frames = [gray, equalized, clahe]
    hits: list[tuple[int, int, int, int]] = []
    min_side = max(48, int(min(crop.size) * 0.055))
    for cascade in cascades:
        if cascade.empty():
            continue
        for frame in frames:
            found = cascade.detectMultiScale(frame, scaleFactor=1.045, minNeighbors=4, minSize=(min_side, min_side))
            for x, y, w, h in found:
                hits.append((int(x + rx1), int(y + ry1), int(w), int(h)))

    clusters: list[dict[str, Any]] = []
    for hit in sorted(hits, key=lambda b: b[2] * b[3], reverse=True):
        matched = None
        for cluster in clusters:
            if _iou(hit, cluster["box"]) >= 0.34:
                matched = cluster
                break
        if matched is None:
            clusters.append({"box": hit, "support": 1})
        else:
            matched["support"] += 1
            bx, by, bw, bh = matched["box"]
            hx, hy, hw, hh = hit
            matched["box"] = (
                int(round((bx + hx) / 2.0)),
                int(round((by + hy) / 2.0)),
                int(round((bw + hw) / 2.0)),
                int(round((bh + hh) / 2.0)),
            )

    eye = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
    for cluster in clusters:
        x, y, w, h = cluster["box"]
        lx1, ly1 = max(0, x - rx1), max(0, y - ry1)
        lx2, ly2 = min(crop.size[0], lx1 + w), min(crop.size[1], ly1 + int(h * 0.68))
        eye_count = 0
        if not eye.empty() and lx2 > lx1 and ly2 > ly1:
            eye_roi = gray[ly1:ly2, lx1:lx2]
            found_eyes = eye.detectMultiScale(eye_roi, scaleFactor=1.08, minNeighbors=4, minSize=(12, 12))
            eye_count = int(len(found_eyes))
        cluster["eye_count"] = eye_count
    return clusters


def source_face_crop(photo3_raw: bytes, log: Any | None = None) -> FaceTarget:
    img = image(photo3_raw)
    clusters = _detect_clusters(img)
    credible = [c for c in clusters if c["support"] >= 2 or c.get("eye_count", 0) >= 1]
    if not credible:
        raise ValueError("photo #3 has no reliably detected face")
    best = max(credible, key=lambda c: (c["box"][2] * c["box"][3], c["support"], c.get("eye_count", 0)))
    box = tuple(best["box"])
    if box[2] < 90 or box[3] < 90:
        raise ValueError("photo #3 face is too small")
    crop_box = _expand(box, img.size, 2.05, 2.38, -0.03)
    raw = jpeg(img.crop(crop_box), max_side=1200, quality=96)
    result = FaceTarget(box, crop_box, raw, int(best["support"]), int(best.get("eye_count", 0)), float(box[2] * box[3]))
    if callable(log):
        log("AI_SELFIE_V257_SOURCE face=%s crop=%s support=%s eyes=%s sha=%s", result.face_box, result.crop_box, result.support, result.eye_count, sha(raw))
    return result


def locate_person_a(composition_raw: bytes, *, scene_image: bool, log: Any | None = None) -> tuple[Any, FaceTarget, dict[str, float]]:
    """Locate PERSON A using a strict left-person ROI and confidence checks.

    No deterministic synthetic target is allowed. If confidence is insufficient,
    the caller must regenerate the Gemini composition instead of swapping a wall.
    """
    img = image(composition_raw)
    iw, ih = img.size
    roi = (int(iw * 0.05), int(ih * 0.06), int(iw * 0.56), int(ih * 0.58))
    clusters = _detect_clusters(img, roi=roi)
    candidates: list[tuple[float, dict[str, Any]]] = []
    target_x = iw * 0.29
    target_y = ih * 0.29

    for c in clusters:
        x, y, w, h = c["box"]
        cx, cy = x + w / 2.0, y + h / 2.0
        hr = h / float(max(1, ih))
        wr = w / float(max(1, iw))
        if not (iw * 0.12 <= cx <= iw * 0.50):
            continue
        if not (ih * 0.10 <= cy <= ih * 0.49):
            continue
        if not (0.065 <= hr <= 0.245 and 0.045 <= wr <= 0.235):
            continue
        support = int(c["support"])
        eyes = int(c.get("eye_count", 0))
        if support < 2 and eyes < 1:
            continue
        distance = ((cx - target_x) / max(1.0, iw)) ** 2 + ((cy - target_y) / max(1.0, ih)) ** 2
        size_bonus = min(3.0, hr * 16.0)
        score = support * 2.2 + min(2, eyes) * 1.6 + size_bonus - distance * 14.0
        candidates.append((score, c))

    if not candidates:
        raise ValueError("PERSON A target not reliably detected inside strict left-person ROI")

    candidates.sort(key=lambda item: item[0], reverse=True)
    score, best = candidates[0]
    if len(candidates) > 1 and score - candidates[1][0] < 0.55:
        raise ValueError("PERSON A target is ambiguous; refusing unsafe face swap")

    box = tuple(best["box"])
    min_px = 180 if scene_image else 125
    min_ratio = 0.105 if scene_image else 0.072
    if box[3] < min_px or box[3] / float(max(1, ih)) < min_ratio:
        raise ValueError("PERSON A face is too small for reliable face swap")

    crop_box = _expand(box, img.size, 2.45, 2.85, 0.015)
    crop_raw = jpeg(img.crop(crop_box), max_side=1400, quality=96)
    metrics = {
        "face_w": float(box[2]),
        "face_h": float(box[3]),
        "face_h_ratio": float(box[3]) / float(max(1, ih)),
        "face_area_ratio": float(box[2] * box[3]) / float(max(1, iw * ih)),
        "support": float(best["support"]),
        "eye_count": float(best.get("eye_count", 0)),
        "score": float(score),
    }
    result = FaceTarget(box, crop_box, crop_raw, int(best["support"]), int(best.get("eye_count", 0)), float(score))
    if callable(log):
        log("AI_SELFIE_V257_TARGET face=%s crop=%s support=%s eyes=%s score=%.3f candidates=%s", result.face_box, result.crop_box, result.support, result.eye_count, result.score, len(candidates))
    return img, result, metrics


def _output_url(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return ""
    output = data.get("output")
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, dict):
        for key in ("image_url", "image", "url", "output_url"):
            value = output.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        images = output.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first.startswith("http"):
                return first
            if isinstance(first, dict):
                for key in ("url", "image_url", "image"):
                    value = first.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return value
    return ""


async def piapi_swap_once(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> bytes:
    key = str(os.getenv("PIAPI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("PIAPI_API_KEY is missing")
    timeout_sec = max(60.0, float(os.getenv("PIAPI_FACE_SWAP_TIMEOUT_SEC") or "180"))
    poll_sec = max(1.0, float(os.getenv("PIAPI_FACE_SWAP_POLL_SEC") or "2"))
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    body = {
        "model": "Qubico/image-toolkit",
        "task_type": "face-swap",
        "input": {
            "target_image": base64.b64encode(target_crop).decode("ascii"),
            "swap_image": base64.b64encode(source_crop).decode("ascii"),
        },
    }
    log("AI_SELFIE_V257_PIAPI trace=%s stage=create target_sha=%s source_sha=%s target_dims=%s source_dims=%s", trace, sha(target_crop), sha(source_crop), dims(target_crop), dims(source_crop))
    timeout = httpx.Timeout(connect=25.0, read=60.0, write=60.0, pool=25.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(PIAPI_TASK_URL, headers=headers, json=body)
        response.raise_for_status()
        created = response.json()
        data = created.get("data") if isinstance(created, dict) else None
        task_id = str((data or {}).get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"PiAPI did not return task_id: {str(created)[:700]}")
        log("AI_SELFIE_V257_PIAPI trace=%s stage=created task_id=%s", trace, task_id)
        deadline = asyncio.get_running_loop().time() + timeout_sec
        last_status = ""
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_sec)
            check = await client.get(f"{PIAPI_TASK_URL}/{task_id}", headers={"x-api-key": key})
            check.raise_for_status()
            payload = check.json()
            pdata = payload.get("data") if isinstance(payload, dict) else None
            status = str((pdata or {}).get("status") or "").strip().lower()
            if status != last_status:
                log("AI_SELFIE_V257_PIAPI trace=%s stage=poll task_id=%s status=%s", trace, task_id, status or "-")
                last_status = status
            if status in {"completed", "success", "succeeded"}:
                url = _output_url(payload)
                if not url:
                    raise RuntimeError("PiAPI completed without image URL")
                out = await client.get(url, timeout=60.0)
                out.raise_for_status()
                raw = bytes(out.content)
                if len(raw) < 1024:
                    raise RuntimeError("PiAPI returned an empty image")
                log("AI_SELFIE_V257_PIAPI trace=%s stage=output task_id=%s sha=%s dims=%s bytes=%s", trace, task_id, sha(raw), dims(raw), len(raw))
                return raw
            if status in {"failed", "error", "cancelled", "canceled"}:
                err = (pdata or {}).get("error") or (pdata or {}).get("detail") or payload.get("message")
                raise RuntimeError(f"PiAPI face swap failed: {str(err)[:900]}")
    raise TimeoutError(f"PiAPI face swap exceeded {int(timeout_sec)} seconds")


def edge_composite(base_img: Any, target: FaceTarget, swapped_crop_raw: bytes) -> bytes:
    """Return scene with PiAPI as central identity authority.

    The provider crop is used throughout the expanded face oval. Only a thin
    feather band at the perimeter blends into the original Gemini scene.
    """
    from PIL import Image, ImageDraw, ImageFilter

    cl, ct, cr, cb = target.crop_box
    cw, ch = cr - cl, cb - ct
    provider = image(swapped_crop_raw).resize((cw, ch), Image.LANCZOS)
    original_crop = base_img.crop(target.crop_box)
    fx, fy, fw, fh = target.face_box
    local_face = (fx - cl, fy - ct, fw, fh)
    region = _expand(local_face, (cw, ch), 1.86, 2.10, 0.012)
    left, top, right, bottom = region
    rw, rh = right - left, bottom - top
    provider_region = provider.crop(region)
    original_region = original_crop.crop(region)

    mask = Image.new("L", (rw, rh), 0)
    draw = ImageDraw.Draw(mask)
    mx = max(2, int(rw * 0.018))
    my = max(2, int(rh * 0.016))
    draw.ellipse((mx, my, rw - mx, rh - my), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(2, int(min(rw, rh) * 0.012))))
    merged_region = Image.composite(provider_region, original_region, mask)
    merged_crop = original_crop.copy()
    merged_crop.paste(merged_region, (left, top))
    output = base_img.copy()
    output.paste(merged_crop, (cl, ct))
    return jpeg(output, max_side=2048, quality=97)


__all__ = [
    "VERSION", "FaceTarget", "sha", "dims", "image", "jpeg",
    "source_face_crop", "locate_person_a", "piapi_swap_once", "edge_composite",
]
