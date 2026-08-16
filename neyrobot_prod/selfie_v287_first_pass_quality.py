# -*- coding: utf-8 -*-
"""V287 first-pass production quality for AI Selfie.

This patch addresses two separate causes of repeated Gemini composition attempts:
1) user uploads were prepared through the legacy generic 1536px reference encoder;
2) full-body AGE/BUILD references visually biased Gemini toward distant framing.

V287 keeps user/hero image bytes lossless whenever the API can accept the original
JPEG/PNG/WebP payload, derives framing-neutral upper-body copies only for the two
AGE/BUILD composition references, and adds a deterministic principal-face-pair
reframe/target rescue. The rescue uses detected face evidence from the first Gemini
image and never invents a random target box. A normal first render therefore should
proceed directly to identity transfer instead of paying the latency of 2-3 renders.
"""
from __future__ import annotations

import base64
import contextlib
from io import BytesIO
from typing import Any

from neyrobot_prod import celebrity_selfie as base
from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal

VERSION = "v287-first-pass-native-input-principal-pair-2026-08-16"
_INSTALLED = False

_ORIGINAL_PREPARE_IMAGE = base._prepare_image
_ORIGINAL_CALL_GOOGLE = v229._call_google
_ORIGINAL_TARGET = terminal._target


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _mime_from_raw(raw: bytes) -> str:
    data = bytes(raw or b"")
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _native_prepare_image(mod: Any, raw: bytes) -> tuple[str, str]:
    """Do not downscale/re-JPEG ordinary Telegram user references a second time.

    Telegram photo messages may already have been compressed by Telegram itself;
    the bot cannot recover pixels that Telegram discarded. What it *can* guarantee
    is that our own Gemini preparation stage does not shrink them again. Documents
    sent as original image files are likewise passed through byte-for-byte.
    """
    data = bytes(raw or b"")
    if len(data) < 1024:
        raise ValueError("reference image is empty")
    mime = _mime_from_raw(data)
    # Gemini inline images comfortably handle the normal Telegram range. Preserve
    # exact bytes up to 14 MiB. Above that, fall back to a very high-quality 4K
    # normalization to keep request size bounded instead of the legacy 1536px path.
    if mime and len(data) <= 14 * 1024 * 1024:
        _log("AI_SELFIE_V287_INPUT status=native_passthrough dims=%s bytes=%s mime=%s sha=%s", fs.dims(data), len(data), mime, fs.sha(data))
        return base64.b64encode(data).decode("ascii"), mime

    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        if max(img.size) > 4096:
            resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            img.thumbnail((4096, 4096), resampling)
        out = BytesIO()
        img.save(out, "JPEG", quality=99, subsampling=0, optimize=True, progressive=False)
        encoded = out.getvalue()
        _log("AI_SELFIE_V287_INPUT status=bounded_4k dims=%s bytes_in=%s bytes_out=%s sha=%s", fs.dims(encoded), len(data), len(encoded), fs.sha(encoded))
        return base64.b64encode(encoded).decode("ascii"), "image/jpeg"
    except Exception:
        return _ORIGINAL_PREPARE_IMAGE(mod, data)


def _upper_body_reference(raw: bytes) -> bytes:
    """Remove full-body camera-distance bias while preserving age/build evidence."""
    data = bytes(raw or b"")
    try:
        img = fs.image(data)
        iw, ih = img.size
        clusters = fs._detect_clusters(img)
        credible = [c for c in clusters if int(c.get("support", 0)) >= 2 or int(c.get("eye_count", 0)) >= 1]
        if not credible:
            return data
        face = max(credible, key=lambda c: c["box"][2] * c["box"][3])
        x, y, w, h = [int(v) for v in face["box"]]
        # Already close enough: keep the exact original bytes.
        if h / float(max(1, ih)) >= 0.20:
            return data
        cx = x + w / 2.0
        top = max(0.0, y - 0.55 * h)
        bottom = min(float(ih), y + 5.5 * h)
        height = max(320.0, bottom - top)
        width = max(320.0, 4.4 * w)
        # Keep the user's upper torso and shoulders, not the original distant scene.
        left = max(0.0, min(float(iw) - width, cx - width / 2.0)) if width < iw else 0.0
        right = min(float(iw), left + width)
        if right - left < width and right >= iw:
            left = max(0.0, right - width)
        bottom = min(float(ih), top + height)
        if bottom - top < height and bottom >= ih:
            top = max(0.0, bottom - height)
        crop = img.crop((int(round(left)), int(round(top)), int(round(right)), int(round(bottom))))
        out = fs.jpeg(crop, max_side=3200, quality=100)
        _log("AI_SELFIE_V287_BODY_REF status=upper_body source=%s face=%s crop=%s out=%s bytes=%s", fs.dims(data), face["box"], (int(left), int(top), int(right), int(bottom)), fs.dims(out), len(out))
        return out
    except Exception as exc:
        _log("AI_SELFIE_V287_BODY_REF status=passthrough error_type=%s error=%s dims=%s", type(exc).__name__, str(exc)[:240], fs.dims(data))
        return data


async def _call_google(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    refs: list[tuple[str, bytes]] = []
    for label, raw in labeled_images:
        data = bytes(raw or b"")
        if "USER AGE/BUILD REFERENCE" in str(label):
            data = _upper_body_reference(data)
            label = str(label) + " CAMERA-FRAMING NOTE: ignore the source photo's camera distance; use it only for age/build/proportions."
        refs.append((str(label), data))
    _log("AI_SELFIE_V287_COMPOSITION stage=%s refs=%s policy=native_inputs+upper_body_body_refs", stage, len(refs))
    return await _ORIGINAL_CALL_GOOGLE(prompt, refs, stage)


def _credible_global(img: Any) -> list[dict[str, Any]]:
    iw, ih = img.size
    result: list[dict[str, Any]] = []
    for c in fs._detect_clusters(img):
        x, y, w, h = [int(v) for v in c["box"]]
        support = int(c.get("support", 0)); eyes = int(c.get("eye_count", 0))
        if support < 2 and eyes < 1:
            continue
        cx = x + w / 2.0; cy = y + h / 2.0
        hr = h / float(max(1, ih)); wr = w / float(max(1, iw))
        if not (0.025 <= hr <= 0.36 and 0.018 <= wr <= 0.34):
            continue
        if not (ih * 0.025 <= cy <= ih * 0.80):
            continue
        item = dict(c); item["_cx"] = cx; item["_cy"] = cy; item["_area"] = w * h
        result.append(item)
    return result


def _principal_pair(img: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    iw, ih = img.size
    faces = _credible_global(img)
    if not faces:
        raise ValueError("V287: no credible face evidence in first composition")

    best_pair: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for i, a in enumerate(faces):
        for b in faces[i + 1:]:
            left, right = (a, b) if a["_cx"] < b["_cx"] else (b, a)
            sep = (right["_cx"] - left["_cx"]) / float(max(1, iw))
            if not (0.09 <= sep <= 0.72):
                continue
            lh = float(left["box"][3]); rh = float(right["box"][3])
            ratio = min(lh, rh) / float(max(lh, rh, 1.0))
            if ratio < 0.34:
                continue
            ydiff = abs(left["_cy"] - right["_cy"]) / float(max(1, ih))
            if ydiff > 0.30:
                continue
            size = (lh + rh) / float(max(1, ih))
            evidence = (int(left.get("support", 0)) + int(right.get("support", 0))) * 0.04
            center_penalty = abs((left["_cx"] + right["_cx"]) / 2.0 / iw - 0.50) * 0.35
            score = size * 4.0 + ratio * 0.8 + evidence - ydiff * 0.9 - center_penalty
            if best_pair is None or score > best_pair[0]:
                best_pair = (score, left, right)
    if best_pair is not None:
        return best_pair[1], best_pair[2]

    # If only PERSON A was detected, still use real face evidence. Prefer the largest
    # credible face on the left 65% rather than failing into another expensive render.
    leftish = [c for c in faces if c["_cx"] <= iw * 0.65]
    if not leftish:
        leftish = faces
    person_a = max(leftish, key=lambda c: (c["_area"], int(c.get("support", 0)), int(c.get("eye_count", 0))))
    return person_a, None


def _aspect_box(iw: int, ih: int, cx: float, cy: float, width: float, height: float) -> tuple[int, int, int, int]:
    aspect = iw / float(max(1, ih))
    width = max(160.0, min(float(iw), width)); height = max(200.0, min(float(ih), height))
    if width / height > aspect:
        height = width / aspect
    else:
        width = height * aspect
    if width > iw:
        width = float(iw); height = width / aspect
    if height > ih:
        height = float(ih); width = height * aspect
    left = max(0.0, min(float(iw) - width, cx - width / 2.0))
    top = max(0.0, min(float(ih) - height, cy - height * 0.36))
    return int(round(left)), int(round(top)), int(round(left + width)), int(round(top + height))


def _first_pass_target(composition: bytes, log: Any):
    """Acquire PERSON A from the first image and reframe geometrically if necessary."""
    from PIL import Image
    img = fs.image(composition).convert("RGB")
    iw, ih = img.size
    person_a, person_b = _principal_pair(img)
    ax, ay, aw, ah = [int(v) for v in person_a["box"]]

    # Aim for ~18% native face height after reframing, matching the camera contract.
    desired_face = max(330.0, ih * 0.18)
    desired_scale = max(1.0, min(4.0, desired_face / float(max(1, ah))))
    crop_h = ih / desired_scale
    crop_w = crop_h * (iw / float(ih))
    acx = person_a["_cx"]; acy = person_a["_cy"]

    if person_b is not None:
        bx, by, bw, bh = [int(v) for v in person_b["box"]]
        pad = max(aw, ah, bw, bh) * 0.78
        min_x = min(ax, bx) - pad; max_x = max(ax + aw, bx + bw) + pad
        # Include heads plus chest/shoulders, not the original full-body camera view.
        min_y = min(ay, by) - max(ah, bh) * 0.70
        max_y = max(ay + ah, by + bh) + max(ah, bh) * 2.45
        crop_w = max(crop_w, max_x - min_x)
        crop_h = max(crop_h, max_y - min_y)
        cx = (person_a["_cx"] + person_b["_cx"]) / 2.0
        cy = (person_a["_cy"] + person_b["_cy"]) / 2.0
    else:
        # Preserve right-side room for PERSON B if its face detector missed.
        crop_w = max(crop_w, iw * 0.52)
        cx = max(iw * 0.44, acx + iw * 0.15)
        cy = acy

    box = _aspect_box(iw, ih, cx, cy, crop_w, crop_h)
    l, t, r, b = box
    scale_x = iw / float(max(1, r - l)); scale_y = ih / float(max(1, b - t))
    if r - l < iw * 0.985 or b - t < ih * 0.985:
        crop = img.crop(box)
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        base_img = crop.resize((iw, ih), resampling)
        nbox = (
            int(round((ax - l) * scale_x)),
            int(round((ay - t) * scale_y)),
            max(1, int(round(aw * scale_x))),
            max(1, int(round(ah * scale_y))),
        )
        normalized = True
    else:
        base_img = img
        nbox = (ax, ay, aw, ah)
        normalized = False

    nx, ny, nw, nh = nbox
    # Bound coordinates after rounding at crop edges.
    nx = max(0, min(iw - 2, nx)); ny = max(0, min(ih - 2, ny))
    nw = max(2, min(iw - nx, nw)); nh = max(2, min(ih - ny, nh))
    nbox = (nx, ny, nw, nh)
    crop_box = fs._expand(nbox, base_img.size, 1.62, 1.88, 0.010)
    crop_raw = fs.jpeg(base_img.crop(crop_box), max_side=2400, quality=100)
    metrics = {
        "face_w": float(nw), "face_h": float(nh), "face_h_ratio": float(nh) / float(max(1, ih)),
        "face_area_ratio": float(nw * nh) / float(max(1, iw * ih)),
        "support": float(person_a.get("support", 0)), "eye_count": float(person_a.get("eye_count", 0)),
        "score": float(person_a.get("_area", 0)), "detector_stage": 7.0,
        "strict_clusters": 0.0, "wide_clusters": float(len(_credible_global(img))),
        "min_px": 0.0, "min_ratio": 0.0,
        "target_face_w_coverage": nw / float(max(1, crop_box[2] - crop_box[0])),
        "target_face_h_coverage": nh / float(max(1, crop_box[3] - crop_box[1])),
    }
    target = fs.FaceTarget(nbox, crop_box, crop_raw, int(person_a.get("support", 0)), int(person_a.get("eye_count", 0)), float(person_a.get("_area", 0)))
    log("AI_SELFIE_V287_TARGET status=accepted_first_pass normalized=%s original_face=%s final_face=%s face_ratio=%.4f crop=%s pair=%s source_dims=%sx%s", normalized, person_a["box"], nbox, metrics["face_h_ratio"], box, bool(person_b), iw, ih)
    return base_img, target, metrics


def _target(composition: bytes, *, scene_image: bool, log: Any):
    try:
        return _ORIGINAL_TARGET(composition, scene_image=scene_image, log=log)
    except ValueError as exc:
        message = str(exc)
        relevant = (
            "face is too small" in message
            or "production floor" in message
            or "target not reliably detected" in message
            or "target is ambiguous" in message
        )
        if not relevant:
            raise
        log("AI_SELFIE_V287_TARGET status=primary_rejected error=%s action=principal_pair_reframe", message[:400])
        return _first_pass_target(composition, log)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    base._prepare_image = _native_prepare_image
    v229._call_google = _call_google
    terminal._target = _target
    setattr(terminal, "_v287_first_pass_quality", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V287 first-pass native-input quality installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
