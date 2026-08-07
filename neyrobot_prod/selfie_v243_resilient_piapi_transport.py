# -*- coding: utf-8 -*-
"""Resilient PiAPI transport for terminal Celebrity Selfie face transfer.

Gemini creates the scene/hero/body. Photo #3 is the sole identity source.
PiAPI performs the terminal isolated face swap. Provider-side model failures are
reported with their real task/error fields instead of being hidden behind five
identical HTTP 500 retries.

Important: PiAPI can return HTTP 200 with status=pending and an empty error
object immediately after task creation. That is a normal accepted task, not a
provider failure. Only terminal failure statuses or a meaningful provider error
must abort the job.
"""
from __future__ import annotations

import asyncio
import base64
import os
from io import BytesIO
from typing import Any

import httpx

VERSION = "v251-piapi-pending-is-not-failure-2026-08-08"
_BIND_COUNT = 0


def _compact_jpeg(raw: bytes, *, max_side: int, quality: int) -> bytes:
    from PIL import Image, ImageOps

    image = Image.open(BytesIO(bytes(raw or b"")))
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = BytesIO()
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


def _provider_failure(payload: Any) -> str:
    """Return concise provider/model failure details, or empty string.

    PiAPI frequently returns an ``error`` object while a task is still pending.
    Empty/default values (including code=0) are not failures. Treat a response as
    failed only when the task has reached a terminal failure status or when the
    provider actually supplied a non-empty error field.
    """
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""

    status = str(data.get("status") or "").strip().lower()
    error = data.get("error")
    failed_status = status in {"failed", "error", "cancelled", "canceled"}

    error_dict = error if isinstance(error, dict) else {}
    code = error_dict.get("code")
    raw = str(error_dict.get("raw_message") or "").strip()
    message = str(error_dict.get("message") or "").strip()
    detail = error_dict.get("detail")

    meaningful_error = (
        code not in (None, "", 0, "0")
        or bool(raw)
        or bool(message)
        or detail not in (None, "", {}, [], 0, "0")
    )

    if not failed_status and not meaningful_error:
        return ""

    task_id = str(data.get("task_id") or "").strip()
    parts = [
        f"task_id={task_id or '-'}",
        f"status={status or '-'}",
        f"provider_code={code if code not in (None, '') else 0}",
    ]
    if raw:
        parts.append(f"raw_message={raw[:1200]}")
    if message and message != raw:
        parts.append(f"message={message[:800]}")
    if detail not in (None, "", {}, [], 0, "0"):
        parts.append(f"detail={str(detail)[:800]}")
    return " | ".join(parts)


async def resilient_piapi_single_face_swap(target_crop: bytes, face_source: bytes, log: Any) -> bytes:
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    key = str(os.getenv("PIAPI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("PIAPI_API_KEY is missing")

    timeout_sec = max(45.0, float(os.getenv("PIAPI_FACE_SWAP_TIMEOUT_SEC") or "180"))
    poll_sec = max(1.0, float(os.getenv("PIAPI_FACE_SWAP_POLL_SEC") or "2"))
    create_attempts = max(2, int(os.getenv("PIAPI_FACE_SWAP_CREATE_ATTEMPTS") or "5"))
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    payload_profiles = [(1280, 94), (1100, 92), (960, 91), (840, 90), (720, 89)]
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    timeout = httpx.Timeout(connect=25.0, read=60.0, write=60.0, pool=25.0)

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
                "AI_SELFIE_V251_CREATE_ATTEMPT attempt=%s/%s target_bytes=%s source_bytes=%s max_side=%s quality=%s",
                attempt, create_attempts, len(compact_target), len(compact_source), max_side, quality,
            )
            try:
                response = await client.post(v237.PIAPI_TASK_URL, headers=headers, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log("AI_SELFIE_V251_CREATE_TRANSPORT_ERROR attempt=%s error=%s", attempt, last_error)
                if attempt < create_attempts:
                    await asyncio.sleep(min(15.0, 2.0 * (2 ** (attempt - 1))))
                    continue
                raise RuntimeError(f"PiAPI create transport failed after {create_attempts} attempts: {last_error}") from exc

            text_preview = (response.text or "")[:900].replace("\n", " ")
            try:
                created = response.json()
            except Exception:
                created = None

            provider_failure = _provider_failure(created)
            if provider_failure:
                log("AI_SELFIE_V251_PROVIDER_MODEL_FAILURE http=%s %s", response.status_code, provider_failure)
                raise RuntimeError(f"PiAPI/Qubico model failure: HTTP {response.status_code} | {provider_failure}")

            log("AI_SELFIE_V251_CREATE_RESPONSE attempt=%s status=%s body=%s", attempt, response.status_code, text_preview)
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}: {text_preview or 'empty response'}"
                retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
                if retryable and attempt < create_attempts:
                    await asyncio.sleep(min(15.0, 2.0 * (2 ** (attempt - 1))))
                    continue
                raise RuntimeError(f"PiAPI task creation failed after {attempt} attempt(s): {last_error}")

            if not isinstance(created, dict):
                last_error = f"invalid JSON: {text_preview}"
                if attempt < create_attempts:
                    await asyncio.sleep(min(15.0, 2.0 * (2 ** (attempt - 1))))
                    continue
                raise RuntimeError(f"PiAPI task creation returned {last_error}")

            data = created.get("data") if isinstance(created, dict) else None
            task_id = str((data or {}).get("task_id") or "").strip()
            create_status = str((data or {}).get("status") or "").strip().lower()
            if task_id:
                log("AI_SELFIE_V251_CREATED task_id=%s attempt=%s status=%s", task_id, attempt, create_status or "-")
                break
            last_error = f"PiAPI did not return task_id: {str(created)[:700]}"
            if attempt < create_attempts:
                await asyncio.sleep(min(15.0, 2.0 * (2 ** (attempt - 1))))
                continue
            raise RuntimeError(last_error)

        if not task_id:
            raise RuntimeError(f"PiAPI create failed after {create_attempts} attempts: {last_error}")

        deadline = asyncio.get_running_loop().time() + timeout_sec
        last_status = ""
        poll_failures = 0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_sec)
            try:
                check = await client.get(f"{v237.PIAPI_TASK_URL}/{task_id}", headers={"x-api-key": key})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                poll_failures += 1
                log("AI_SELFIE_V251_POLL_TRANSPORT_RETRY task_id=%s failures=%s error=%r", task_id, poll_failures, exc)
                if poll_failures >= 8:
                    raise RuntimeError(f"PiAPI polling repeatedly failed: {type(exc).__name__}: {exc}") from exc
                continue

            preview = (check.text or "")[:900].replace("\n", " ")
            try:
                payload = check.json()
            except Exception:
                payload = None

            if check.status_code >= 400:
                poll_failures += 1
                log("AI_SELFIE_V251_POLL_RETRY task_id=%s status=%s failures=%s body=%s", task_id, check.status_code, poll_failures, preview)
                if (check.status_code in {408, 425, 429} or check.status_code >= 500) and poll_failures < 8:
                    await asyncio.sleep(min(10.0, poll_failures * 1.5))
                    continue
                raise RuntimeError(f"PiAPI poll failed: HTTP {check.status_code}: {preview}")

            poll_failures = 0
            if not isinstance(payload, dict):
                raise RuntimeError(f"PiAPI poll returned invalid JSON: {preview}")

            provider_failure = _provider_failure(payload)
            if provider_failure:
                log("AI_SELFIE_V251_PROVIDER_MODEL_FAILURE_POLL http=%s %s", check.status_code, provider_failure)
                raise RuntimeError(f"PiAPI/Qubico model failure while polling: HTTP {check.status_code} | {provider_failure}")

            pdata = payload.get("data") if isinstance(payload, dict) else None
            status = str((pdata or {}).get("status") or "").strip().lower()
            if status != last_status:
                log("AI_SELFIE_V251_STATUS task_id=%s status=%s", task_id, status or "-")
                last_status = status

            if status in {"completed", "success", "succeeded"}:
                url = _output_url(payload)
                if not url:
                    raise RuntimeError(f"PiAPI completed without image URL: {str(payload)[:800]}")
                image_response = await client.get(url, timeout=60.0)
                if image_response.status_code >= 400:
                    raise RuntimeError(f"PiAPI output download failed: HTTP {image_response.status_code}")
                final = bytes(image_response.content)
                if len(final) < 1024:
                    raise RuntimeError("PiAPI returned an empty image")
                log("AI_SELFIE_V251_OUTPUT_OK task_id=%s bytes=%s", task_id, len(final))
                return final

            # pending/processing/queued/running are normal non-terminal states.
            # Keep polling until completed, a real provider failure, or timeout.

    raise TimeoutError(f"PiAPI face swap exceeded {int(timeout_sec)} seconds")


def install() -> bool:
    global _BIND_COUNT
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    v237._piapi_single_face_swap = resilient_piapi_single_face_swap
    v237.VERSION = VERSION
    _BIND_COUNT += 1
    if _BIND_COUNT == 1 or _BIND_COUNT % 600 == 0:
        print(f"[neyrobot-prod] V251 PiAPI transport bound version={VERSION} bind_count={_BIND_COUNT}", flush=True)
    return True


install()

__all__ = ["VERSION", "install", "resilient_piapi_single_face_swap", "_provider_failure"]
