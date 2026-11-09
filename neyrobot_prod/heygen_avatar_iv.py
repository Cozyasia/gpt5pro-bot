"""HeyGen Avatar IV image/audio transport for NEYRONIX.

Uses HeyGen v3's arbitrary-image + audio-to-video endpoint. This is the
route for stylized/non-human mascots when Kling identify-face rejects them.
"""
from __future__ import annotations

import asyncio
import mimetypes
import os
from typing import Any

import httpx

BASE_URL = "https://api.heygen.com"


class HeyGenAvatarIVError(RuntimeError):
    """A safe, user-facing HeyGen Avatar IV transport error."""


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or payload.get("data") or payload
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("detail") or detail
        return str(detail)[:500]
    return str(payload)[:500]


def _value(payload: Any, names: tuple[str, ...]) -> str:
    if isinstance(payload, dict):
        for name in names:
            value = payload.get(name)
            if value:
                return str(value)
        for key in ("data", "result", "asset", "video"):
            value = payload.get(key)
            found = _value(value, names)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _value(item, names)
            if found:
                return found
    return ""


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key}


async def _upload_asset(client: httpx.AsyncClient, api_key: str, raw: bytes, filename: str) -> str:
    if not raw:
        raise HeyGenAvatarIVError("Пустой файл для HeyGen Avatar IV.")
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = await client.post(
        BASE_URL + "/v3/assets",
        headers=_headers(api_key),
        files={"file": (filename, raw, mime)},
    )
    if response.status_code >= 400:
        raise HeyGenAvatarIVError("HeyGen не принял файл: " + _message(response))
    asset_id = _value(response.json(), ("asset_id", "id"))
    if not asset_id:
        raise HeyGenAvatarIVError("HeyGen не вернул идентификатор загруженного файла.")
    return asset_id


async def create_image_audio_video(
    api_key: str,
    image_bytes: bytes,
    audio_bytes: bytes,
    *,
    image_name: str = "neyronix.png",
    audio_name: str = "voice.mp3",
    title: str = "NEYRONIX Avatar IV",
    aspect_ratio: str = "auto",
    resolution: str = "1080p",
) -> str:
    """Upload image/audio and return asynchronous HeyGen video_id."""
    if not api_key:
        raise HeyGenAvatarIVError("HEYGEN_API_KEY не задан в Render.")
    async with httpx.AsyncClient(timeout=180) as client:
        image_asset_id = await _upload_asset(client, api_key, image_bytes, image_name)
        audio_asset_id = await _upload_asset(client, api_key, audio_bytes, audio_name)
        payload = {
            "type": "image",
            # HeyGen v3 image mode expects the image discriminator object.
            # Avatar IV is the default engine for arbitrary-image input;
            # passing an engine object here is rejected by the image schema.
            "image": {"type": "asset_id", "asset_id": image_asset_id},
            "audio_asset_id": audio_asset_id,
            "title": title,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "expressiveness": "high",
            "motion_prompt": (
                "Friendly NEYRONIX robot mascot speaking directly to the viewer. "
                "Keep the exact character identity, colors and logo. "
                "Natural mouth movement, gentle blinking, small welcoming hand gestures."
            ),
        }
        response = await client.post(
            BASE_URL + "/v3/videos",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json=payload,
        )
        if response.status_code >= 400:
            raise HeyGenAvatarIVError("HeyGen не создал видео: " + _message(response))
        video_id = _value(response.json(), ("video_id", "id"))
        if not video_id:
            raise HeyGenAvatarIVError("HeyGen не вернул video_id.")
        return video_id



async def create_nonhuman_reference_video(
    api_key: str,
    image_bytes: bytes,
    audio_bytes: bytes,
    *,
    duration_seconds: int = 8,
    image_name: str = "neyronix.png",
    audio_name: str = "voice.mp3",
    title: str = "NEYRONIX HeyGen Video",
    speech_text: str = "",
    aspect_ratio: str = "auto",
    resolution: str = "768p",
) -> str:
    """Create a non-human mascot clip with HeyGen Video reference-to-video.

    Avatar IV's direct talking-avatar endpoint may reject a stylized mascot
    when its face detector cannot classify it as human-like. HeyGen Video's
    reference mode accepts an image plus an audio reference and is intended
    for products, characters, and other non-human subjects.
    """
    if not api_key:
        raise HeyGenAvatarIVError("HEYGEN_API_KEY не задан в Render.")
    duration = max(5, min(15, int(duration_seconds or 8)))
    allowed_aspect_ratios = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"}
    safe_aspect_ratio = aspect_ratio if aspect_ratio in allowed_aspect_ratios else "adaptive"
    async with httpx.AsyncClient(timeout=180) as client:
        image_asset_id = await _upload_asset(client, api_key, image_bytes, image_name)
        audio_asset_id = await _upload_asset(client, api_key, audio_bytes, audio_name)
        payload = {
            "model": "heygen-video-1",
            "mode": "reference_to_video",
            "prompt": (
                "Use <Picture 1> as the exact visual identity of the friendly "
                "NEYRONIX robot mascot. Keep its white-and-blue rounded body, "
                "black face visor, cyan eyes, antennae, chest emblem and NEYRONIX "
                "branding recognizable throughout the entire shot. The robot "
                "speaks directly to the viewer with natural mouth movement timed "
                "to <Audio 1>, gentle blinking and small welcoming hand gestures. "
                "Around the robot, show five large friendly floating folder cards, "
                "appearing one by one and remaining readable in Russian: "
                "«Медицина», «Обучение», «Видео», «Документы», «Профиль». "
                "These are the only additional words allowed on screen. Keep the "
                "robot centered and preserve the original friendly cartoon "
                "appearance. No new characters, no scene cuts, no distorted limbs, "
                "no logo changes, no random text, no gibberish, no music. "
                "Use <Audio 1> as the only voice reference. Speak the dialogue "
                "once from beginning to end; do not repeat any word or sentence."
                + (f' The exact Russian dialogue is: «{speech_text.strip()[:1200]}». '
                   "Say it exactly once and stop when it ends."
                   if speech_text and speech_text.strip() else "")
            ),
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": safe_aspect_ratio,
            "prompt_enhancement": "disabled",
            "reference_images": [
                {"type": "asset_id", "asset_id": image_asset_id},
            ],
            "reference_audio": [
                {"type": "asset_id", "asset_id": audio_asset_id},
            ],
        }
        response = await client.post(
            BASE_URL + "/v3/models/videos",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json=payload,
        )
        if response.status_code >= 400:
            raise HeyGenAvatarIVError(
                "HeyGen Video не создал видео: " + _message(response)
            )
        video_id = _value(response.json(), ("video_id", "id"))
        if not video_id:
            raise HeyGenAvatarIVError("HeyGen Video не вернул video_id.")
        return video_id


async def poll_model_video(api_key: str, video_id: str, *, max_wait_seconds: int = 1200) -> str:
    """Poll a HeyGen Video model generation."""
    if not api_key or not video_id:
        raise HeyGenAvatarIVError("Не хватает данных для проверки HeyGen Video.")
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(max(1, max_wait_seconds // 10)):
            response = await client.get(
                BASE_URL + "/v3/models/videos/" + video_id,
                headers=_headers(api_key),
            )
            if response.status_code >= 400:
                raise HeyGenAvatarIVError(
                    "Ошибка статуса HeyGen Video: " + _message(response)
                )
            payload = response.json()
            data = payload.get("data", payload) if isinstance(payload, dict) else {}
            status = str(data.get("status") or data.get("state") or "").lower()
            if status in {"completed", "complete", "success", "succeeded"}:
                url = data.get("video_url") or data.get("url")
                if url:
                    return str(url)
                raise HeyGenAvatarIVError(
                    "HeyGen Video завершил задачу без ссылки на видео."
                )
            if status in {"failed", "error", "cancelled", "canceled"}:
                reason = data.get("failure_message") or data.get("error") or status
                raise HeyGenAvatarIVError(
                    "HeyGen Video завершил задачу с ошибкой: " + str(reason)[:400]
                )
            await asyncio.sleep(10)
    raise HeyGenAvatarIVError(
        "HeyGen Video ещё обрабатывает видео. Повторите проверку позже."
    )

async def poll_video(api_key: str, video_id: str, *, max_wait_seconds: int = 1200) -> str:
    if not api_key or not video_id:
        raise HeyGenAvatarIVError("Не хватает данных для проверки HeyGen.")
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(max(1, max_wait_seconds // 10)):
            response = await client.get(
                BASE_URL + "/v3/videos/" + video_id,
                headers=_headers(api_key),
            )
            if response.status_code >= 400:
                raise HeyGenAvatarIVError("Ошибка статуса HeyGen: " + _message(response))
            payload = response.json()
            data = payload.get("data", payload) if isinstance(payload, dict) else {}
            status = str(data.get("status") or data.get("state") or "").lower()
            if status in {"completed", "complete", "success", "succeeded"}:
                url = data.get("video_url") or data.get("url")
                if url:
                    return str(url)
                raise HeyGenAvatarIVError("HeyGen завершил задачу без ссылки на видео.")
            if status in {"failed", "error", "cancelled", "canceled"}:
                reason = data.get("failure_message") or data.get("error") or status
                raise HeyGenAvatarIVError("HeyGen завершил задачу с ошибкой: " + str(reason)[:400])
            await asyncio.sleep(10)
    raise HeyGenAvatarIVError("HeyGen ещё обрабатывает видео. Повторите проверку позже.")
