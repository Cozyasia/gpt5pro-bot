"""HeyGen v3 API adapter for Russian talking-presenter videos.

The v3 endpoint is a paid asynchronous mutation.  A unique idempotency key
keeps a transport retry from accidentally creating a second video.
"""
from __future__ import annotations

import asyncio
import uuid

import httpx


BASE_URL = "https://api.heygen.com"


class UncertainHeyGenSubmission(RuntimeError):
    """The request may have reached HeyGen, so it must not be blindly retried."""


class HeyGenValidationError(RuntimeError):
    """HeyGen explicitly rejected the request before a video was created."""


def _validation_message(response: httpx.Response) -> str:
    """Return provider detail without leaking request credentials or full payloads."""
    try:
        body = response.json()
    except ValueError:
        return f"HeyGen rejected the request ({response.status_code})"
    detail = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(detail, dict):
        return f"HeyGen rejected the request ({response.status_code})"
    code = str(detail.get("code") or "invalid_parameter")
    message = str(detail.get("message") or "")[:300]
    param = str(detail.get("param") or "")[:120]
    suffix = f"; parameter: {param}" if param else ""
    return f"HeyGen rejected the request ({response.status_code}, {code}): {message}{suffix}".rstrip(": ")


async def create_presenter_video(
    api_key: str,
    avatar_id: str,
    voice_id: str,
    script: str,
    *,
    title: str = "Neyro-Bot Studio",
    idempotency_key: str | None = None,
) -> str:
    if not all((api_key, avatar_id, voice_id, script.strip())):
        raise ValueError("HEYGEN_API_KEY, avatar, voice and script are required")

    # `type` became mandatory in the current v3 contract.  Without it HeyGen
    # responds 400 before it can create or bill a video.
    payload = {
        "type": "avatar",
        "avatar_id": avatar_id,
        "voice_id": voice_id,
        "script": script.strip(),
        "title": title,
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "voice_settings": {"locale": "ru-RU"},
    }
    request_key = idempotency_key or uuid.uuid4().hex
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Idempotency-Key": request_key,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(BASE_URL + "/v3/videos", headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise UncertainHeyGenSubmission("HeyGen POST status unknown: do not resubmit") from exc
        if 400 <= response.status_code < 500:
            raise HeyGenValidationError(_validation_message(response))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UncertainHeyGenSubmission(
                f"HeyGen server returned {response.status_code}; do not resubmit"
            ) from exc
        data = response.json()
        for node in (data, data.get("data"), data.get("result")):
            if isinstance(node, dict):
                for field in ("video_id", "id"):
                    if node.get(field):
                        return str(node[field])
        raise UncertainHeyGenSubmission("HeyGen response lacks video ID; do not resubmit")


async def poll_presenter_video(api_key: str, video_id: str, *, max_wait_seconds: int = 1200) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(max_wait_seconds // 10):
            response = await client.get(BASE_URL + "/v3/videos/" + video_id, headers={"X-Api-Key": api_key})
            response.raise_for_status()
            body = response.json()
            data = body.get("data", body) if isinstance(body, dict) else {}
            if not isinstance(data, dict):
                raise RuntimeError("Unexpected HeyGen status response")
            status = str(data.get("status") or data.get("state") or "").lower()
            if status in ("completed", "success", "succeeded"):
                url = data.get("video_url") or data.get("url")
                if not url and isinstance(data.get("video"), dict):
                    url = data["video"].get("url")
                if not url:
                    raise RuntimeError("HeyGen completed without a video URL")
                return str(url)
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError("HeyGen video failed: " + str(data.get("error") or status)[:300])
            await asyncio.sleep(10)
    raise TimeoutError("HeyGen processing continues; retain video ID for polling")
