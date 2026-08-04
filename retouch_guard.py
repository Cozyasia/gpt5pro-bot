# -*- coding: utf-8 -*-
"""Production-safe text-driven retouching.

The provider may return a fully regenerated frame. This module never exposes that
frame directly: it builds a conservative mask from the user's location words and
composites only the masked pixels back onto the untouched original.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from io import BytesIO
from typing import Iterable

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

log = logging.getLogger("gpt-bot.retouch")

_RETRY_DELAYS = (2.0, 4.0, 8.0)


def _has_any(text: str, words: Iterable[str]) -> bool:
    return any(word in text for word in words)


def _normalized_png(data: bytes, max_side: int = 2048) -> tuple[Image.Image, bytes]:
    image = Image.open(BytesIO(data))
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, "PNG", optimize=True)
    return image, out.getvalue()


def _regions_from_instruction(text: str, width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Translate common RU/EN location descriptions into conservative rectangles."""
    t = re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()
    regions: list[tuple[int, int, int, int]] = []

    top = _has_any(t, ("сверху", "вверху", "верхн", "top"))
    bottom = _has_any(t, ("снизу", "внизу", "нижн", "bottom"))
    left = _has_any(t, ("слева", "левом", "левой", "left"))
    right = _has_any(t, ("справа", "правом", "правой", "right"))
    center = _has_any(t, ("по центру", "в центре", "посередине", "center", "middle"))

    # Corner requests get a focused mask. Percentages deliberately include a
    # safety margin so text shadows and logo outlines are covered as well.
    if top and right:
        regions.append((int(width * 0.58), 0, width, int(height * 0.38)))
    if top and left:
        regions.append((0, 0, int(width * 0.42), int(height * 0.38)))
    if bottom and right and not center:
        regions.append((int(width * 0.58), int(height * 0.62), width, height))
    if bottom and left and not center:
        regions.append((0, int(height * 0.62), int(width * 0.42), height))
    if bottom and center:
        regions.append((int(width * 0.18), int(height * 0.66), int(width * 0.82), height))
    if top and center:
        regions.append((int(width * 0.18), 0, int(width * 0.82), int(height * 0.34)))

    if not regions:
        if top:
            regions.append((0, 0, width, int(height * 0.30)))
        if bottom:
            regions.append((0, int(height * 0.70), width, height))
        if left:
            regions.append((0, 0, int(width * 0.32), height))
        if right:
            regions.append((int(width * 0.68), 0, width, height))
        if center:
            regions.append((int(width * 0.22), int(height * 0.22), int(width * 0.78), int(height * 0.78)))

    # A phrase can describe two objects, e.g. "logo top-right and text bottom".
    # If a top corner and a second bottom target are both named, include the
    # bottom band independently; do not let the first object's "right" leak into
    # the location of the second object.
    if top and bottom and not center:
        bottom_band = (0, int(height * 0.72), width, height)
        if bottom_band not in regions:
            regions.append(bottom_band)

    # Remove duplicates while preserving order.
    unique: list[tuple[int, int, int, int]] = []
    for region in regions:
        if region not in unique:
            unique.append(region)
    return unique


def _build_masks(size: tuple[int, int], regions: list[tuple[int, int, int, int]]) -> tuple[Image.Image, Image.Image]:
    width, height = size
    hard = Image.new("L", size, 0)
    draw = ImageDraw.Draw(hard)
    pad = max(8, int(min(width, height) * 0.012))
    for x1, y1, x2, y2 in regions:
        draw.rectangle((max(0, x1 - pad), max(0, y1 - pad), min(width, x2 + pad), min(height, y2 + pad)), fill=255)
    feather = max(4, int(min(width, height) * 0.008))
    soft = hard.filter(ImageFilter.GaussianBlur(feather))
    return hard, soft


def _openai_mask_png(edit_area: Image.Image) -> bytes:
    # OpenAI edits: transparent pixels are editable; opaque pixels are preserved.
    rgba = Image.new("RGBA", edit_area.size, (255, 255, 255, 255))
    alpha = ImageOps.invert(edit_area)
    rgba.putalpha(alpha)
    out = BytesIO()
    rgba.save(out, "PNG", optimize=True)
    return out.getvalue()


def _strict_prompt(user_instruction: str) -> str:
    return (
        "Perform a precise professional photo retouch. "
        "Remove only the object, watermark, logo or text explicitly requested by the user inside the transparent masked area. "
        "Reconstruct the missing local background naturally from immediately surrounding pixels. "
        "Do not redesign, restyle or regenerate the photograph. Do not alter people, faces, bodies, furniture, walls, windows, "
        "lighting, colors, perspective, geometry, sharpness, camera characteristics or composition. "
        "Do not add any new object, text, logo, pattern or decoration. Preserve photographic noise and texture. "
        f"User request: {user_instruction.strip()}"
    )


async def _request_edit(*, image_png: bytes, mask_png: bytes, instruction: str, api_key: str,
                        base_url: str, model: str, quality: str, timeout_s: float) -> bytes:
    url = f"{base_url.rstrip('/')}/images/edits"
    headers = {"Authorization": f"Bearer {api_key}"}
    files = {
        "image": ("original.png", image_png, "image/png"),
        "mask": ("mask.png", mask_png, "image/png"),
    }
    data = {
        "model": model or "gpt-image-1",
        "prompt": _strict_prompt(instruction),
        "quality": quality or "medium",
        "size": "auto",
        "output_format": "png",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=30.0), follow_redirects=True) as client:
        response = await client.post(url, headers=headers, files=files, data=data)
        if response.status_code >= 400:
            # Some compatible endpoints reject optional fields supported by OpenAI.
            if response.status_code in (400, 422):
                data.pop("output_format", None)
                data.pop("size", None)
                response = await client.post(url, headers=headers, files=files, data=data)
            response.raise_for_status()
        payload = response.json() or {}

    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError("Images edit returned no data")
    item = rows[0] or {}
    if item.get("b64_json"):
        import base64
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0), follow_redirects=True) as client:
            downloaded = await client.get(item["url"])
            downloaded.raise_for_status()
            return downloaded.content
    raise RuntimeError("Images edit returned neither b64_json nor url")


def _outside_change_ratio(original: Image.Image, edited: Image.Image, hard_mask: Image.Image) -> float:
    edited = edited.resize(original.size, Image.Resampling.LANCZOS).convert("RGB")
    diff = ImageChops.difference(original, edited).convert("L")
    outside = ImageOps.invert(hard_mask)
    weighted = ImageChops.multiply(diff, outside)
    histogram = weighted.histogram()
    changed = sum(count for value, count in enumerate(histogram) if value >= 12)
    outside_pixels = max(1, sum(outside.histogram()[1:]))
    return changed / outside_pixels


async def guarded_openai_retouch(img_bytes: bytes, user_instruction: str, *, api_key: str,
                                 base_url: str = "https://api.openai.com/v1", model: str = "gpt-image-1",
                                 quality: str = "medium", timeout_s: float = 180.0) -> bytes | None:
    """Retouch only a localized mask and return an original-preserving composite."""
    if not api_key or api_key.startswith("sk-or-"):
        return None

    try:
        original, image_png = _normalized_png(img_bytes)
    except Exception:
        log.exception("retouch: invalid input image")
        return None

    regions = _regions_from_instruction(user_instruction, *original.size)
    if not regions:
        # Fail closed: without a location, a whole-frame edit would recreate the
        # exact regression this module is designed to prevent.
        log.warning("retouch rejected: no location found in instruction=%r", user_instruction[:300])
        return None

    hard_mask, soft_mask = _build_masks(original.size, regions)
    mask_png = _openai_mask_png(hard_mask)
    last_error: Exception | None = None

    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            generated = await _request_edit(
                image_png=image_png,
                mask_png=mask_png,
                instruction=user_instruction,
                api_key=api_key,
                base_url=base_url,
                model=model,
                quality=quality,
                timeout_s=timeout_s,
            )
            edited = Image.open(BytesIO(generated)).convert("RGB").resize(original.size, Image.Resampling.LANCZOS)
            outside_ratio = _outside_change_ratio(original, edited, hard_mask)
            log.info("retouch provider attempt=%s outside_change_ratio=%.5f regions=%s", attempt, outside_ratio, regions)

            # The final composite mathematically preserves every pixel outside the
            # feathered mask even if the provider regenerated the whole frame.
            result = Image.composite(edited, original, soft_mask)
            out = BytesIO()
            result.save(out, "PNG", optimize=True)
            return out.getvalue()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, RuntimeError, OSError) as exc:
            last_error = exc
            log.warning("retouch attempt %s/%s failed: %s", attempt, len(_RETRY_DELAYS), exc)
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(delay + random.uniform(0.0, 0.5))

    log.error("retouch failed after retries: %s", last_error)
    return None
