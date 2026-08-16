# -*- coding: utf-8 -*-
"""V284 production guardrails for AI Selfie.

Goals:
- make Gemini frame PERSON A close enough from attempt 1 instead of relying on retries;
- deterministically reframe a too-wide generated composition before face swap when
  the model still ignores the camera contract;
- require a fresh hero selection after a new 3-photo user upload, so stale hero/
  scene state cannot silently skip the hero step.
"""
from __future__ import annotations

import contextlib
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v219_triref_scene_owner as owner

VERSION = "v284-close-framing-hero-gate-2026-08-16"
_INSTALLED = False

_ORIGINAL_PROMPT = terminal._prompt
_ORIGINAL_TARGET = terminal._target
_ORIGINAL_RESET_PHOTOS = owner._reset_photos


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    base = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    label = str(shot_label or "").lower()
    is_selfie = "селфи" in label or "selfie" in label
    if is_selfie:
        framing = (
            " V284 CAMERA DISTANCE LOCK — ABSOLUTE: compose the FINAL FRONT-CAMERA FRAME as a CLOSE TWO-PERSON SELFIE, "
            "shoulders-up or chest-up. PERSON A and PERSON B must be close to the lens and together occupy most of the frame. "
            "PERSON A's face height MUST be about 18-25% of the full 2304px image height (roughly 415-575 native pixels). "
            "PERSON B must be similarly prominent. DO NOT show either principal person full-body, knee-up, or as a small figure. "
            "DO NOT prioritize showing the room/stadium/location over the people. Background is secondary and may be cropped. "
            "The top of both heads must be visible, shoulders/chest visible, and both faces must remain unobstructed. "
            "If the draft would make either principal face smaller than roughly one-sixth of image height, move the camera closer BEFORE rendering."
        )
    else:
        framing = (
            " V284 CAMERA DISTANCE LOCK — ABSOLUTE: use a close two-person event portrait, chest-up or at most waist-up. "
            "PERSON A's face height MUST be about 16-23% of the full 2304px image height (roughly 370-530 native pixels). "
            "Do not use a wide establishing shot or full-body framing. People dominate the frame; environment is secondary."
        )
    return base + framing


def _credible_clusters(img: Any) -> list[dict[str, Any]]:
    iw, ih = img.size
    clusters = fs._detect_clusters(img)
    out: list[dict[str, Any]] = []
    for c in clusters:
        x, y, w, h = c["box"]
        cx, cy = x + w / 2.0, y + h / 2.0
        hr = h / float(max(1, ih))
        wr = w / float(max(1, iw))
        support = int(c.get("support", 0))
        eyes = int(c.get("eye_count", 0))
        if support < 2 and eyes < 1:
            continue
        if not (0.035 <= hr <= 0.32 and 0.022 <= wr <= 0.30):
            continue
        if not (ih * 0.035 <= cy <= ih * 0.74):
            continue
        item = dict(c)
        item["_cx"] = cx
        item["_cy"] = cy
        item["_area"] = w * h
        out.append(item)
    return out


def _aspect_crop_box(iw: int, ih: int, cx: float, cy: float, width: float, height: float) -> tuple[int, int, int, int]:
    aspect = iw / float(max(1, ih))
    width = max(64.0, min(float(iw), width))
    height = max(64.0, min(float(ih), height))
    if width / height > aspect:
        height = width / aspect
    else:
        width = height * aspect
    if width > iw:
        width = float(iw); height = width / aspect
    if height > ih:
        height = float(ih); width = height * aspect
    left = max(0.0, min(float(iw) - width, cx - width / 2.0))
    top = max(0.0, min(float(ih) - height, cy - height * 0.38))
    return (int(round(left)), int(round(top)), int(round(left + width)), int(round(top + height)))


def _normalize_wide_composition(composition: bytes, log: Any) -> bytes | None:
    """Crop a Gemini wide shot around the two principal faces, then restore native canvas size.

    This is a deterministic geometry operation only; it does not invent face pixels or
    run another generative model. V280 later owns the final identity/detail transfer.
    """
    from PIL import Image

    img = fs.image(composition).convert("RGB")
    iw, ih = img.size
    clusters = _credible_clusters(img)
    if not clusters:
        return None

    left_candidates = [c for c in clusters if c["_cx"] <= iw * 0.60]
    if not left_candidates:
        return None
    # PERSON A is contractually the left principal person. Prefer a large, credible
    # face near the expected left-person zone rather than a tiny background face.
    def left_score(c: dict[str, Any]) -> float:
        x, y, w, h = c["box"]
        distance = abs(c["_cx"] / iw - 0.30) + 0.55 * abs(c["_cy"] / ih - 0.29)
        return (h / ih) * 8.0 + int(c.get("support", 0)) * 0.55 + int(c.get("eye_count", 0)) * 0.45 - distance

    person_a = max(left_candidates, key=left_score)
    ax, ay, aw, ah = person_a["box"]
    acx = person_a["_cx"]

    right_candidates = [c for c in clusters if c["_cx"] > acx + iw * 0.10 and c["_cx"] <= iw * 0.94]
    person_b = None
    if right_candidates:
        person_b = max(right_candidates, key=lambda c: (c["box"][3] * 2 + c["box"][2]) + int(c.get("support", 0)) * 35)

    # Aim for >=~260px Person-A face after reframing. That clears the V283 bounded
    # rescue floor while V280 replaces the identity-critical facial core from photo #3.
    desired_scale = max(1.0, min(3.0, 270.0 / float(max(1, ah))))
    crop_w = iw / desired_scale
    crop_h = ih / desired_scale

    if person_b is not None:
        bx, by, bw, bh = person_b["box"]
        min_x = min(ax, bx) - max(aw, bw) * 0.65
        max_x = max(ax + aw, bx + bw) + max(aw, bw) * 0.65
        pair_span = max_x - min_x
        crop_w = max(crop_w, pair_span)
        face_mid_x = (acx + person_b["_cx"]) / 2.0
        face_mid_y = (person_a["_cy"] + person_b["_cy"]) / 2.0
    else:
        # Keep generous room to the right for PERSON B even if the detector did not
        # confidently classify that face.
        face_mid_x = max(iw * 0.46, acx + iw * 0.18)
        face_mid_y = person_a["_cy"]
        crop_w = max(crop_w, iw * 0.58)

    crop_h = max(crop_h, crop_w / (iw / float(ih)))
    box = _aspect_crop_box(iw, ih, face_mid_x, face_mid_y, crop_w, crop_h)
    l, t, r, b = box
    if r - l >= iw * 0.96 or b - t >= ih * 0.96:
        return None

    crop = img.crop(box)
    resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    normalized = crop.resize((iw, ih), resampling)
    raw = fs.jpeg(normalized, max_side=max(iw, ih), quality=100)
    scale = iw / float(max(1, r - l))
    log(
        "AI_SELFIE_V284_NORMALIZE status=applied original=%sx%s crop=%s scale=%.3f person_a_face=%s expected_face_after=%.1f clusters=%s",
        iw, ih, box, scale, person_a["box"], ah * scale, len(clusters),
    )
    return raw


def _target(composition: bytes, *, scene_image: bool, log: Any):
    try:
        return _ORIGINAL_TARGET(composition, scene_image=scene_image, log=log)
    except ValueError as exc:
        message = str(exc)
        relevant = (
            "face is too small" in message
            or "production floor" in message
            or "target not reliably detected" in message
        )
        if not relevant:
            raise
        normalized = _normalize_wide_composition(composition, log)
        if not normalized:
            raise
        try:
            result = _ORIGINAL_TARGET(normalized, scene_image=scene_image, log=log)
            log("AI_SELFIE_V284_NORMALIZE status=accepted original_error=%s", message[:240])
            return result
        except Exception as second:
            log(
                "AI_SELFIE_V284_NORMALIZE status=rejected original_error=%s normalized_error_type=%s normalized_error=%s",
                message[:220], type(second).__name__, str(second)[:300],
            )
            raise second


def _reset_photos(context: Any, first: bytes | None = None) -> None:
    _ORIGINAL_RESET_PHOTOS(context, first)
    # New user-photo set starts a new ordered AI-selfie job. Never inherit a hero,
    # scene or shot from the previous job, otherwise the UI can skip mandatory steps.
    for key in (
        "cs201_character", "cs201_country", "cs215_shot_mode", "cs215_scene_mode",
        "cs215_scene_text", "cs215_scene_image", "cs215_scene_label", "cs215_wait_scene_text",
        "cs215_await_scene_image", "cs201_wait_custom_scene",
    ):
        context.user_data.pop(key, None)
    with contextlib.suppress(Exception):
        context.user_data["cs284_fresh_hero_required"] = True


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._prompt = _prompt
    terminal._target = _target
    owner._reset_photos = _reset_photos
    _INSTALLED = True
    print(f"[neyrobot-prod] V284 close framing + mandatory hero gate installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
