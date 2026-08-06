# -*- coding: utf-8 -*-
"""V243 resilient PiAPI transport for terminal Celebrity Selfie face transfer.

Keeps the existing architecture unchanged:
- Gemini creates scene, hero and user body only.
- photo #3 is the sole identity source.
- PiAPI performs the terminal single-face swap on isolated crops.

This patch only makes the external PiAPI task transport resilient to transient 429/5xx
responses and oversized/fragile payloads. It never falls back to Gemini identity generation.
"""
from __future__ import annotations

import asyncio
import base64
import os
from io import BytesIO
from typing import Any

import httpx

VERSION = "v243-resilient-piapi-transport-2026-08-06"
_INSTALLED = False


def _compact_jpeg(raw: bytes, *, max_side: int, quality: int) -> bytes:
    from PIL import Image, ImageOps

    image = Image.open(BytesIO(bytes(raw or b"")))
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = BytesIO()
    # Baseline JPEG is deliberately used here. Some upstream image workers are less
    # reliable with progressive JPEG payloads embedded as base64.
    image.save(out, "JPEG", quality=quality, optimize=True, progressive=False)
    return out.getvalue()


def _b64(raw: bytes) -> str:
    return base64.b64encode(bytes(raw)).decode("ascii")


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


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    async def resilient_piapi_single_face_swap(target_crop: bytes, face_source: bytes, log: Any) -> bytes:
        key = str(os.getenv("PIAPI_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("PIAPI_API_KEY is missing")

        timeout_sec = max(45.0, float(os.getenv("PIAPI_FACE_SWAP_TIMEOUT_SEC") or "180"))
        poll_sec = max(1.0, float(os.getenv("PIAPI_FACE_SWAP_POLL_SEC") or "2"))
        create_attempts = max(2, int(os.getenv("PIAPI_FACE_SWAP_CREATE_ATTEMPTS") or "4"))
        headers = {"x-api-key": key, "Content-Type": "application/json"}

        # Attempt 1 keeps more detail. Later attempts progressively reduce payload size
        # while preserving enough facial detail for identity transfer.
        payload_profiles = [
            (1280, 94),
            (1100, 92),
            (960, 91),
            (840, 90),
        ]
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        timeout = httpx.Timeout(connect=20.0, read=45.0, write=45.0, pool=20.0)

        async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
            task_id = ""
            last_error = ""
            for attempt in range(1, create_attempts + 1):
                max_side, quality = payload_profiles[min(attempt - 1, len(payload_profiles) - 1)]
                compact_target = _compact_jpeg(target_crop, max_side=max_side, quality=quality)
                compact_source = _compact_jpeg(face_source, max_side=max_side, quality=quality)
                body = {
                    "model": "Qubico/image-toolkit",
                    "task_type": "face-swap",
                    "input": {
                        "target_image": _b64(compact_target),
                        "swap_image": _b64(compact_source),
                    },
                }
                log(
                    "AI_SELFIE_V243_CREATE_ATTEMPT attempt=%s/%s target_bytes=%s source_bytes=%s max_side=%s quality=%s",
                    attempt, create_attempts, len(compact_target), len(compact_source), max_side, quality,
                )
                try:
                    response = await client.post(v237.PIAPI_TASK_URL, headers=headers, json=body)
                    text_preview = (response.text or "")[:500].replace("\n", " ")
                    log(
                        "AI_SELFIE_V243_CREATE_RESPONSE attempt=%s status=%s body=%s",
                        attempt, response.status_code, text_preview,
                    )
                    if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
                        last_error = f"HTTP {response.status_code}: {text_preview}"
                        if attempt < create_attempts:
                            await asyncio.sleep(min(12.0, 1.5 * (2 ** (attempt - 1))))
                            continue
                    response.raise_for_status()
                    created = response.json()
                    data = created.get("data") if isinstance(created, dict) else None
                    task_id = str((data or {}).get("task_id") or "").strip()
                    if not task_id:
                        last_error = f"PiAPI did not return task_id: {str(created)[:500]}"
                        if attempt < create_attempts:
                            await asyncio.sleep(min(12.0, 1.5 * (2 ** (attempt - 1))))
                            continue
                        raise RuntimeError(last_error)
                    log("AI_SELFIE_V243_CREATED task_id=%s attempt=%s", task_id, attempt)
                    break
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    log("AI_SELFIE_V243_CREATE_TRANSPORT_ERROR attempt=%s error=%s", attempt, last_error)
                    if attempt < create_attempts:
                        await asyncio.sleep(min(12.0, 1.5 * (2 ** (attempt - 1))))
                        continue
                    raise RuntimeError(f"PiAPI create transport failed after {create_attempts} attempts: {last_error}") from exc

            if not task_id:
                raise RuntimeError(f"PiAPI create failed after {create_attempts} attempts: {last_error}")

            deadline = asyncio.get_running_loop().time() + timeout_sec
            last_status = "pending"
            poll_failures = 0
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(poll_sec)
                try:
                    check = await client.get(f"{v237.PIAPI_TASK_URL}/{task_id}", headers={"x-api-key": key})
                    if check.status_code in {408, 425, 429} or check.status_code >= 500:
                        poll_failures += 1
                        log(
                            "AI_SELFIE_V243_POLL_RETRY task_id=%s status=%s failures=%s body=%s",
                            task_id, check.status_code, poll_failures, (check.text or "")[:300].replace("\n", " "),
                        )
                        if poll_failures >= 8:
                            check.raise_for_status()
                        await asyncio.sleep(min(10.0, poll_failures * 1.5))
                        continue
                    check.raise_for_status()
                    poll_failures = 0
                    payload = check.json()
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    poll_failures += 1
                    log("AI_SELFIE_V243_POLL_TRANSPORT_RETRY task_id=%s failures=%s error=%r", task_id, poll_failures, exc)
                    if poll_failures >= 8:
                        raise RuntimeError(f"PiAPI polling repeatedly failed: {type(exc).__name__}: {exc}") from exc
                    continue

                pdata = payload.get("data") if isinstance(payload, dict) else None
                status = str((pdata or {}).get("status") or "").lower()
                if status != last_status:
                    log("AI_SELFIE_V243_STATUS task_id=%s status=%s", task_id, status)
                    last_status = status
                if status in {"completed", "success", "succeeded"}:
                    url = _output_url(payload)
                    if not url:
                        raise RuntimeError(f"PiAPI completed without image URL: {str(payload)[:800]}")
                    image_response = await client.get(url, timeout=60.0)
                    image_response.raise_for_status()
                    final = bytes(image_response.content)
                    if len(final) < 1024:
                        raise RuntimeError("PiAPI returned an empty image")
                    log("AI_SELFIE_V243_OUTPUT_OK task_id=%s bytes=%s", task_id, len(final))
                    return final
                if status in {"failed", "error", "cancelled", "canceled"}:
                    error = (pdata or {}).get("error") or (pdata or {}).get("detail") or payload.get("message")
                    raise RuntimeError(f"PiAPI face swap task failed: {str(error)[:700]}")

        raise TimeoutError(f"PiAPI face swap exceeded {int(timeout_sec)} seconds")

    v237._piapi_single_face_swap = resilient_piapi_single_face_swap
    v237.VERSION = VERSION
    _INSTALLED = True
    print(f"[neyrobot-prod] V243 resilient PiAPI transport installed version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "install"]
