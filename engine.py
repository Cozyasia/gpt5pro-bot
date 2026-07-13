# -*- coding: utf-8 -*-
"""Async CometAPI helpers for Neyro-Bot GPT 5 Studio.

Network-only module. Telegram UX, billing, retries visible to the user and
moderation messages remain in ``main.py``.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

import httpx


class CometError(RuntimeError):
    """Raised when CometAPI rejects a request or a task fails."""


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def _extract_url(obj: Any) -> str | None:
    if isinstance(obj, str):
        return obj if obj.startswith(("http://", "https://")) else None
    if isinstance(obj, list):
        for item in obj:
            url = _extract_url(item)
            if url:
                return url
        return None
    if isinstance(obj, dict):
        for key in (
            "video_url", "videoUrl", "image_url", "imageUrl", "audio_url",
            "url", "uri", "download_url", "downloadUrl", "output",
            "outputs", "assets", "result", "data",
        ):
            if key in obj:
                url = _extract_url(obj[key])
                if url:
                    return url
        for value in obj.values():
            url = _extract_url(value)
            if url:
                return url
    return None


def _extract_task_id(data: dict[str, Any]) -> str:
    candidates: Iterable[Any] = (
        data.get("id"), data.get("task_id"), data.get("taskId"),
        data.get("generation_id"), data.get("video_id"), data.get("result"),
        (data.get("data") or {}).get("id") if isinstance(data.get("data"), dict) else None,
        (data.get("result") or {}).get("id") if isinstance(data.get("result"), dict) else None,
    )
    for value in candidates:
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def _decode_b64(value: str) -> bytes:
    try:
        raw = value.split(",", 1)[-1] if value.startswith("data:") else value
        return base64.b64decode(raw)
    except Exception as exc:
        raise CometError(f"Invalid base64 input: {exc}") from exc


@dataclass(slots=True)
class CometConfig:
    base_url: str
    api_key: str

    @classmethod
    def from_env(cls) -> "CometConfig":
        base_url = _env("COMET_BASE_URL", "https://api.cometapi.com").rstrip("/")
        api_key = _env("COMET_API_KEY") or _env("COMETAPI_KEY")
        if not api_key:
            raise CometError("COMET_API_KEY is not configured")
        return cls(base_url=base_url, api_key=api_key)


class CometClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("timeout") is not None:
            timeout_s = float(kwargs["timeout"])
        cfg = CometConfig.from_env() if not api_key else None
        self.base_url = (base_url or (cfg.base_url if cfg else "https://api.cometapi.com")).rstrip("/")
        self.api_key = api_key or (cfg.api_key if cfg else "")
        if not self.api_key:
            raise CometError("COMET_API_KEY is not configured")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=True,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "neyro-bot/86",
            },
        )

    async def __aenter__(self) -> "CometClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = dict(extra_headers or {})
        response = await self._client.request(
            method,
            f"{self.base_url}{path}",
            json=json_body,
            data=data,
            files=files,
            headers=headers or None,
        )
        try:
            payload = response.json() if response.content else {}
        except Exception:
            payload = {"raw": response.text[:2000]}
        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error") or payload.get("description") or payload
            raise CometError(f"Comet HTTP {response.status_code}: {message}")
        return payload if isinstance(payload, dict) else {"data": payload}

    async def _download(self, url: str) -> bytes:
        response = await self._client.get(url, headers={"Accept": "*/*"})
        response.raise_for_status()
        if not response.content:
            raise CometError("Provider returned an empty file")
        return response.content

    async def _poll(
        self,
        paths: Iterable[str],
        task_id: str,
        *,
        timeout_s: int = 900,
        interval_s: float = 4.0,
        success_states: tuple[str, ...] = ("SUCCESS", "SUCCEEDED", "COMPLETED", "DONE"),
    ) -> tuple[dict[str, Any], str]:
        deadline = asyncio.get_running_loop().time() + timeout_s
        last: Any = None
        while asyncio.get_running_loop().time() < deadline:
            for template in paths:
                try:
                    data = await self._request_json("GET", template.format(id=task_id))
                except CometError as exc:
                    last = str(exc)
                    continue
                last = data
                status = str(data.get("status") or data.get("state") or "").upper()
                url = _extract_url(data)
                if status in success_states and url:
                    return data, url
                if status in ("FAILURE", "FAILED", "ERROR", "CANCELLED", "CANCELED"):
                    reason = data.get("failReason") or data.get("error") or data.get("description") or data
                    raise CometError(f"Task {task_id} failed: {reason}")
            await asyncio.sleep(interval_s)
        raise CometError(f"Timeout waiting for task {task_id}. Last response: {last}")

    async def sora_text_to_video(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
        model: str | None = None,
    ) -> tuple[bytes, str]:
        size = {"9:16": "720x1280", "1:1": "1024x1024"}.get(aspect_ratio, "1280x720")
        payload = {
            "model": model or _env("SORA_MODEL", "sora-2"),
            "prompt": prompt,
            "seconds": str(duration_s),
            "size": size,
        }
        data = await self._request_json("POST", _env("SORA_CREATE_PATH", "/v1/videos"), json_body=payload)
        ready = _extract_url(data)
        if ready:
            return await self._download(ready), "sora.mp4"
        task_id = _extract_task_id(data)
        if not task_id:
            raise CometError(f"Sora did not return a task id: {data}")
        _, url = await self._poll(
            (_env("SORA_STATUS_PATH", "/v1/videos/{id}"), "/v1/videos/{id}"),
            task_id,
        )
        return await self._download(url), f"sora_{task_id}.mp4"

    async def sora2_text_to_video(self, prompt: str, **kwargs: Any) -> tuple[bytes, str]:
        return await self.sora_text_to_video(prompt, **kwargs)

    async def kling_text_to_video(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
        model: str | None = None,
    ) -> tuple[bytes, str]:
        payload = {
            "model": model or _env("KLING_MODEL", "kling-v1-6"),
            "prompt": prompt,
            "duration": str(duration_s),
            "aspect_ratio": aspect_ratio,
            "mode": "std",
        }
        create_path = _env("KLING_TEXT_CREATE_PATH", "/kling/v1/videos/text2video")
        data = await self._request_json("POST", create_path, json_body=payload)
        ready = _extract_url(data)
        if ready:
            return await self._download(ready), "kling.mp4"
        task_id = _extract_task_id(data)
        if not task_id:
            raise CometError(f"Kling did not return a task id: {data}")
        _, url = await self._poll(
            (
                _env("KLING_TEXT_STATUS_PATH", "/kling/v1/videos/text2video/{id}"),
                "/kling/v1/videos/{id}",
                "/v1/tasks/{id}",
            ),
            task_id,
        )
        return await self._download(url), f"kling_{task_id}.mp4"

    async def runway_text_to_video(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
        model: str | None = None,
        timeout_s: int = 1200,
    ) -> tuple[bytes, str]:
        # Official Runway Gen-4.5 text→video uses image_to_video with promptImage omitted.
        # Comet may expose the same compatibility surface when its Runway channel is available.
        ratio = "720:1280" if aspect_ratio in {"9:16", "3:4", "4:5"} else "1280:720"
        payload = {
            "model": model or _env("RUNWAY_TEXT_MODEL", "gen4.5"),
            "promptText": prompt,
            "duration": max(2, min(10, int(duration_s))),
            "ratio": ratio,
        }
        data = await self._request_json(
            "POST",
            _env("RUNWAY_COMET_CREATE_PATH", "/runwayml/v1/image_to_video"),
            json_body=payload,
            extra_headers={"X-Runway-Version": _env("RUNWAY_API_VERSION", "2024-11-06")},
        )
        ready = _extract_url(data)
        if ready:
            return await self._download(ready), "runway.mp4"
        task_id = _extract_task_id(data)
        if not task_id:
            raise CometError(f"Runway did not return a task id: {data}")
        _, url = await self._poll(
            (_env("RUNWAY_COMET_STATUS_PATH", "/runwayml/v1/tasks/{id}"), "/runwayml/v1/tasks/{id}"),
            task_id,
            timeout_s=timeout_s,
        )
        return await self._download(url), f"runway_{task_id}.mp4"

    async def kling_image_to_video(
        self,
        prompt: str,
        b64: str,
        *,
        mime: str = "image/jpeg",
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> tuple[bytes, str]:
        image = _decode_b64(b64)
        payload = {"prompt": prompt, "duration": str(duration_s), "aspect_ratio": aspect_ratio, "mode": "std"}
        data = await self._request_json(
            "POST",
            _env("KLING_CREATE_PATH", "/kling/v1/videos/image2video"),
            data={"json": json.dumps(payload)},
            files={"image": ("image.jpg", image, mime)},
        )
        ready = _extract_url(data)
        if ready:
            return await self._download(ready), "kling_i2v.mp4"
        task_id = _extract_task_id(data)
        if not task_id:
            raise CometError(f"Kling did not return a task id: {data}")
        _, url = await self._poll(("/kling/v1/videos/image2video/{id}", "/kling/v1/videos/{id}"), task_id)
        return await self._download(url), f"kling_{task_id}.mp4"

    async def sora_image_to_video(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
        mime: str = "image/jpeg",
    ) -> tuple[bytes, str]:
        payload = {"prompt": prompt, "duration": duration_s, "aspect_ratio": aspect_ratio}
        data = await self._request_json(
            "POST",
            "/sora/v1/videos/image2video",
            data={"json": json.dumps(payload)},
            files={"image": ("image.jpg", image_bytes, mime)},
        )
        ready = _extract_url(data)
        if ready:
            return await self._download(ready), "sora_i2v.mp4"
        task_id = _extract_task_id(data)
        if not task_id:
            raise CometError(f"Sora did not return a task id: {data}")
        _, url = await self._poll(("/sora/v1/videos/{id}", "/v1/videos/{id}"), task_id)
        return await self._download(url), f"sora_{task_id}.mp4"

    async def sora2_image_to_video(
        self,
        prompt: str,
        b64: str,
        mime: str = "image/jpeg",
        **kwargs: Any,
    ) -> tuple[bytes, str]:
        return await self.sora_image_to_video(_decode_b64(b64), prompt, mime=mime, **kwargs)

    async def runway_image_to_video(
        self,
        prompt: str,
        image_url: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
        model: str = "gen4_turbo",
        timeout_s: int = 1200,
    ) -> tuple[bytes, str]:
        if not image_url:
            raise CometError("image_url is required")
        ratio = "720:1280" if aspect_ratio in {"9:16", "3:4", "4:5"} else "1280:720"
        payload = {
            "model": model,
            "promptImage": image_url,
            "promptText": prompt,
            "duration": max(2, min(10, int(duration_s))),
            "ratio": ratio,
        }
        data = await self._request_json(
            "POST",
            _env("RUNWAY_COMET_CREATE_PATH", "/runwayml/v1/image_to_video"),
            json_body=payload,
            extra_headers={"X-Runway-Version": _env("RUNWAY_API_VERSION", "2024-11-06")},
        )
        ready = _extract_url(data)
        if ready:
            return await self._download(ready), "runway_i2v.mp4"
        task_id = _extract_task_id(data)
        if not task_id:
            raise CometError(f"Runway did not return a task id: {data}")
        _, url = await self._poll(("/runwayml/v1/tasks/{id}",), task_id, timeout_s=timeout_s)
        return await self._download(url), f"runway_{task_id}.mp4"

    async def midjourney_imagine(
        self,
        prompt: str,
        *,
        mode: str = "FAST",
        version: str = "7",
        timeout_s: int = 600,
    ) -> tuple[bytes, str]:
        prompt = prompt.strip()
        if version and "--v " not in prompt and "--version " not in prompt:
            prompt = f"{prompt} --v {version}"
        mode = mode.upper()
        prefix = {"FAST": "/mj-fast", "TURBO": "/mj-turbo"}.get(mode, "")
        payload = {
            "botType": "MID_JOURNEY",
            "prompt": prompt,
            "accountFilter": {"modes": [mode if mode in ("FAST", "TURBO", "RELAX") else "FAST"]},
        }
        data = await self._request_json("POST", f"{prefix}/mj/submit/imagine", json_body=payload)
        task_id = str(data.get("result") or _extract_task_id(data)).strip()
        if not task_id:
            raise CometError(f"Midjourney did not return a task id: {data}")
        _, image_url = await self._poll(
            ("/mj/task/{id}/fetch",),
            task_id,
            timeout_s=timeout_s,
            success_states=("SUCCESS",),
        )
        return await self._download(image_url), f"midjourney_{task_id}.jpg"
