# -*- coding: utf-8 -*-
"""CometAPI client helpers for GPT-5 PRO Bot.

This module intentionally contains ONLY network logic for Comet-backed engines
(Kling / Sora / Runway). Main bot code should call these methods and handle UX.

Base URL example: https://api.cometapi.com
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx


class CometError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else default


@dataclass
class CometConfig:
    base_url: str
    api_key: str

    @staticmethod
    def from_env() -> Optional["CometConfig"]:
        base = _env("COMET_BASE_URL")
        key = _env("COMET_API_KEY")
        if not base or not key:
            return None
        base = base.rstrip("/")
        return CometConfig(base_url=base, api_key=key)


class CometClient:
    """Thin async client around CometAPI.

    Notes:
    - We always pass Bearer token in Authorization.
    - We do NOT assume Comet returns JSON on errors; we parse safely.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout_s: float = 120.0, **kwargs):
        # main.py may pass timeout=...
        if "timeout" in kwargs and kwargs["timeout"] is not None:
            timeout_s = float(kwargs["timeout"])
        cfg = CometConfig.from_env() if (base_url is None or api_key is None) else None
        self.base_url = (base_url or (cfg.base_url if cfg else "")).rstrip("/")
        self.api_key = api_key or (cfg.api_key if cfg else "")
        if not self.base_url or not self.api_key:
            raise CometError("Comet API is not configured (need COMET_BASE_URL and COMET_API_KEY).")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_s))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            # some gateways are picky about UA
            "User-Agent": "gpt5pro-bot/1.0",
        }

    async def _request_json(self, method: str, path: str, *, params: Dict[str, Any] | None = None,
                            json_body: Dict[str, Any] | None = None,
                            data: Dict[str, Any] | None = None,
                            files: Any = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = await self._client.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            data=data,
            files=files,
        )
        content_type = (resp.headers.get("content-type") or "").lower()
        text = resp.text

        def _as_json() -> Dict[str, Any]:
            try:
                return resp.json()
            except Exception:
                # best-effort parse if gateway returns text
                return {"raw": text}

        if resp.status_code >= 400:
            payload = _as_json()
            msg = payload.get("message") or payload.get("error") or payload.get("raw") or text
            raise CometError(f"HTTP {resp.status_code} from Comet: {msg}")

        # normal success
        if "json" in content_type:
            return _as_json()
        # some endpoints might return empty body
        if not text.strip():
            return {}
        # attempt parse anyway
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}

    async def _download_bytes(self, url: str) -> bytes:
        r = await self._client.get(url, headers={"Accept": "*/*", "User-Agent": "gpt5pro-bot/1.0"})
        r.raise_for_status()
        return r.content

    
import base64


def _b64_to_bytes(b64_str: str) -> bytes:
    try:
        return base64.b64decode(b64_str)
    except Exception as e:
        raise CometError(f"Invalid base64 image: {e}")
# -------------------- KLING --------------------

    async def kling_image_to_video(
        self,
        prompt: str,
        b64: str,
        *,
        mime: str = "image/jpeg",
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> Tuple[bytes, str]:
        image_bytes = _b64_to_bytes(b64)
        if not image_bytes:
            raise CometError("Kling: image is empty (0 bytes).")

        payload = {
            "prompt": prompt,
            "duration": duration_s,
            "aspect_ratio": aspect_ratio,
        }

        data = await self._request_json(
            "POST",
            "/kling/v1/videos/image2video",
            data={"json": json.dumps(payload)},
            files={"image": ("image.jpg", image_bytes, mime)},
        )

        # Comet usually returns id or data.id
        task_id = data.get("id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise CometError(f"Kling: unexpected response: {data}")

        # poll status
        video_url = await self._poll_video_url("/kling/v1/videos/{id}", task_id)
        video_bytes = await self._download_bytes(video_url)
        return video_bytes, f"kling_{task_id}.mp4"

    # -------------------- SORA --------------------

    async def sora_text_to_video(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> Tuple[bytes, str]:
        payload = {
            "prompt": prompt,
            "duration": duration_s,
            "aspect_ratio": aspect_ratio,
        }
        data = await self._request_json("POST", "/sora/v1/videos", json_body=payload)
        task_id = data.get("id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise CometError(f"Sora: unexpected response: {data}")
        video_url = await self._poll_video_url("/sora/v1/videos/{id}", task_id)
        video_bytes = await self._download_bytes(video_url)
        return video_bytes, f"sora_{task_id}.mp4"

    async def sora_image_to_video(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> Tuple[bytes, str]:
        if not image_bytes:
            raise CometError("Sora: image is empty (0 bytes).")
        payload = {
            "prompt": prompt,
            "duration": duration_s,
            "aspect_ratio": aspect_ratio,
        }
        data = await self._request_json(
            "POST",
            "/sora/v1/videos/image2video",
            data={"json": json.dumps(payload)},
            files={"image": ("image.jpg", image_bytes, mime)},
        )
        task_id = data.get("id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise CometError(f"Sora: unexpected response: {data}")
        video_url = await self._poll_video_url("/sora/v1/videos/{id}", task_id)
        video_bytes = await self._download_bytes(video_url)
        return video_bytes, f"sora_{task_id}.mp4"

    # -------------------- RUNWAY (via Comet) --------------------

    async def runway_image_to_video(
        self,
        prompt: str,
        image_url: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
        model: str = "gen4",
    ) -> Tuple[bytes, str]:
        if not image_url:
            raise CometError("Runway: image_url is empty.")
        image_bytes = await self._download_bytes(image_url)
        if not image_bytes:
            raise CometError("Runway: image is empty (0 bytes).")

        # Comet-runway is task-based.
        payload = {
            "model": model,
            "prompt": prompt,
            "ratio": aspect_ratio,
            "duration": duration_s,
        }

        data = await self._request_json(
            "POST",
            "/runwayml/v1/tasks",
            data={"json": json.dumps(payload)},
            files={"image": ("image.jpg", image_bytes, mime)},
        )
        task_id = data.get("id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise CometError(f"Runway: unexpected response: {data}")

        video_url = await self._poll_runway_task(task_id)
        video_bytes = await self._download_bytes(video_url)
        return video_bytes, f"runway_{task_id}.mp4"

    async def _poll_runway_task(self, task_id: str, *, timeout_s: int = 300, interval_s: float = 3.0) -> str:
        deadline = asyncio.get_running_loop().time() + timeout_s
        last = None
        while asyncio.get_running_loop().time() < deadline:
            data = await self._request_json("GET", f"/runwayml/v1/tasks/{task_id}")
            last = data
            status = (data.get("status") or data.get("state") or "").lower()

            # try to find a usable video URL
            out_url = None
            for key in ("output", "outputs", "result", "assets"):
                obj = data.get(key)
                if isinstance(obj, str) and obj.startswith("http"):
                    out_url = obj
                    break
                if isinstance(obj, dict):
                    for k2 in ("video", "video_url", "url"):
                        v = obj.get(k2)
                        if isinstance(v, str) and v.startswith("http"):
                            out_url = v
                            break
                if out_url:
                    break

            if status in ("succeeded", "success", "completed", "done") and out_url:
                return out_url
            if status in ("failed", "error", "canceled", "cancelled"):
                raise CometError(f"Runway: task failed: {data}")

            await asyncio.sleep(interval_s)

        raise CometError(f"Runway: timeout waiting for task. Last response: {last}")


    async def kling_text_to_video(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> Tuple[bytes, str]:
        payload = {
            "prompt": prompt,
            "duration": duration_s,
            "aspect_ratio": aspect_ratio,
        }
        data = await self._request_json("POST", "/kling/v1/videos", json_body=payload)
        task_id = data.get("id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise CometError(f"Kling: unexpected response: {data}")
        video_url = await self._poll_video_url("/kling/v1/videos/{id}", task_id)
        video_bytes = await self._download_bytes(video_url)
        return video_bytes, f"kling_{task_id}.mp4"

    # Backward-compatible aliases used in main.py
    async def sora2_text_to_video(self, prompt: str, **kw) -> Tuple[bytes, str]:
        return await self.sora_text_to_video(prompt, **kw)

    async def sora2_image_to_video(self, prompt: str, b64: str, mime: str = "image/jpeg", **kw) -> Tuple[bytes, str]:
        # main passes base64 and mime
        image_bytes = _b64_to_bytes(b64)
        return await self.sora_image_to_video(image_bytes, prompt, **kw)

    async def runway_text_to_video(self, prompt: str, **kw) -> Tuple[bytes, str]:
        # Some flows in main may call text->video.
        payload = {
            "prompt": prompt,
            "duration": kw.pop("duration_s", kw.pop("duration", 5)),
            "ratio": kw.pop("aspect_ratio", kw.pop("ratio", "16:9")),
            "model": kw.pop("model", "gen4"),
        }
        data = await self._request_json("POST", "/runwayml/v1/tasks", json_body=payload)
        task_id = data.get("id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise CometError(f"Runway: unexpected response: {data}")
        video_url = await self._poll_runway_task(task_id, timeout_s=kw.pop("timeout_s", 300))
        video_bytes = await self._download_bytes(video_url)
        return video_bytes, f"runway_{task_id}.mp4"
    # -------------------- common pollers --------------------

    async def _poll_video_url(self, template: str, task_id: str, *, timeout_s: int = 300, interval_s: float = 3.0) -> str:
        deadline = asyncio.get_running_loop().time() + timeout_s
        last = None
        while asyncio.get_running_loop().time() < deadline:
            data = await self._request_json("GET", template.format(id=task_id))
            last = data
            status = (data.get("status") or data.get("state") or "").lower()

            # common shapes
            out_url = None
            if isinstance(data.get("url"), str) and data["url"].startswith("http"):
                out_url = data["url"]
            assets = data.get("assets")
            if not out_url and isinstance(assets, dict):
                for k in ("video", "video_url", "url"):
                    v = assets.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        out_url = v
                        break
            if not out_url:
                output = data.get("output")
                if isinstance(output, dict):
                    v = output.get("url") or output.get("video")
                    if isinstance(v, str) and v.startswith("http"):
                        out_url = v

            if status in ("succeeded", "success", "completed", "done") and out_url:
                return out_url
            if status in ("failed", "error", "canceled", "cancelled"):
                raise CometError(f"Task failed: {data}")

            await asyncio.sleep(interval_s)

        raise CometError(f"Timeout waiting for task. Last response: {last}")
