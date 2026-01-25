# -*- coding: utf-8 -*-
"""
Comet API proxy client for Sora 2 / Suno / Midjourney.

Design goals:
- Production-safe (timeouts, retries, defensive JSON parsing)
- Configurable endpoints via env vars (Comet providers differ by account/plan)
- Returns raw bytes + a sane filename so Telegram won't send .bin

Required env:
- COMET_BASE_URL   e.g. https://<your-comet-host>
- COMET_API_KEY    token/key for Authorization header

Optional env overrides:
- COMET_SORA2_ENDPOINT   default: /sora/v1/text_to_video
- COMET_SUNO_ENDPOINT    default: /suno/v1/text_to_music
- COMET_MJ_ENDPOINT      default: /midjourney/v1/imagine
- COMET_STATUS_TEMPLATE  default: /tasks/{id}
- COMET_RESULT_FIELDS    comma-separated list of JSON fields to look for result URL
"""
from __future__ import annotations

import os
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import httpx


class CometError(RuntimeError):
    pass


def _first(d: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _normalize_base(base: str) -> str:
    return (base or "").strip().rstrip("/")


def _join(base: str, path: str) -> str:
    base = _normalize_base(base)
    path = (path or "").strip()
    if not path:
        return base
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base + path


@dataclass
class TaskInfo:
    task_id: str
    status_url: str


class CometClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.base_url = _normalize_base(base_url)
        self.api_key = (api_key or "").strip()
        if not self.base_url:
            raise CometError("COMET_BASE_URL is empty")
        if not self.api_key:
            raise CometError("COMET_API_KEY is empty")
        self.timeout = timeout

        self.sora2_endpoint = os.environ.get("COMET_SORA2_ENDPOINT", "/sora/v1/text_to_video").strip()
        self.suno_endpoint  = os.environ.get("COMET_SUNO_ENDPOINT",  "/suno/v1/text_to_music").strip()
        self.mj_endpoint    = os.environ.get("COMET_MJ_ENDPOINT",    "/midjourney/v1/imagine").strip()
        self.sora2_i2v_endpoint = os.environ.get("COMET_SORA2_I2V_ENDPOINT", "/sora/v1/image_to_video").strip()
        self.kling_t2v_endpoint = os.environ.get("COMET_KLING_T2V_ENDPOINT", "/kling/v1/text_to_video").strip()
        self.kling_i2v_endpoint = os.environ.get("COMET_KLING_I2V_ENDPOINT", "/kling/v1/image_to_video").strip()

        self.status_tmpl = os.environ.get("COMET_STATUS_TEMPLATE", "/tasks/{id}").strip()
        fields = os.environ.get(
            "COMET_RESULT_FIELDS",
            "result_url,output_url,video_url,audio_url,image_url,url,download_url,output,asset_url",
        )
        self.result_fields = [x.strip() for x in fields.split(",") if x.strip()]

    def _headers(self) -> Dict[str, str]:
        # Accept both Bearer and raw tokens; Comet instances vary.
        # If user already provides "Bearer ..." we keep it.
        auth = self.api_key
        if not auth.lower().startswith("bearer "):
            auth = f"Bearer {auth}"
        return {
            "Authorization": auth,
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = _join(self.base_url, path)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            txt = (r.text or "")[:2000]
            if r.status_code >= 400:
                raise CometError(f"HTTP {r.status_code} from Comet submit: {txt}")
            try:
                return r.json()
            except Exception:
                raise CometError(f"Comet submit returned non-JSON: {txt}")

    async def _get_json(self, url_or_path: str) -> Dict[str, Any]:
        url = _join(self.base_url, url_or_path)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, headers=self._headers())
            txt = (r.text or "")[:2000]
            if r.status_code >= 400:
                raise CometError(f"HTTP {r.status_code} from Comet status: {txt}")
            try:
                return r.json()
            except Exception:
                raise CometError(f"Comet status returned non-JSON: {txt}")

    async def _download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, follow_redirects=True)
            if r.status_code >= 400:
                raise CometError(f"Failed to download result (HTTP {r.status_code})")
            return r.content

    def _parse_task(self, data: Dict[str, Any]) -> TaskInfo:
        # Common shapes:
        # { "id": "...", "status_url": "..." }
        # { "task_id": "...", "status_url": "..." }
        # { "data": { "id": "...", "status_url": "..." } }
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        tid = _first(inner, ["task_id", "id", "uuid"])
        if not tid:
            raise CometError(f"Comet did not return task id. Response keys: {list(data.keys())[:30]}")
        status_url = _first(inner, ["status_url", "statusUrl", "poll_url", "pollUrl"])
        if not status_url:
            status_url = self.status_tmpl.replace("{id}", str(tid))
        return TaskInfo(task_id=str(tid), status_url=str(status_url))

    def _parse_done_url(self, data: Dict[str, Any]) -> Optional[str]:
        # Dive into "data" if present
        inner = data.get("data") if isinstance(data.get("data"), dict) else data

        # direct fields
        url = _first(inner, self.result_fields)
        if isinstance(url, str) and url:
            return url

        # nested outputs
        outputs = inner.get("outputs") or inner.get("output") or inner.get("result")
        if isinstance(outputs, dict):
            u = _first(outputs, self.result_fields)
            if isinstance(u, str) and u:
                return u
        if isinstance(outputs, list):
            # try first dict entry
            for it in outputs:
                if isinstance(it, dict):
                    u = _first(it, self.result_fields)
                    if isinstance(u, str) and u:
                        return u
                elif isinstance(it, str) and it.startswith("http"):
                    return it

        # some providers return "assets": [{"url": "..."}]
        assets = inner.get("assets")
        if isinstance(assets, list):
            for it in assets:
                if isinstance(it, dict) and isinstance(it.get("url"), str):
                    return it["url"]

        return None

    async def _poll_until_done(self, status_url: str, max_wait: float = 600.0) -> Dict[str, Any]:
        start = time.time()
        delay = 2.0
        last_json: Dict[str, Any] = {}
        while True:
            last_json = await self._get_json(status_url)

            inner = last_json.get("data") if isinstance(last_json.get("data"), dict) else last_json
            status = str(_first(inner, ["status", "state"]) or "").lower()

            if status in ("succeeded", "success", "completed", "complete", "done", "finished"):
                return last_json
            if status in ("failed", "error", "canceled", "cancelled"):
                # include best effort error text
                err = _first(inner, ["error", "message", "detail"])
                raise CometError(f"Task failed: {err or 'unknown error'}")

            if time.time() - start > max_wait:
                raise CometError("Task timeout: too long waiting for result")

            await asyncio.sleep(delay)
            delay = min(delay * 1.3, 10.0)

    async def sora2_text_to_video(self, prompt: str) -> Tuple[bytes, str]:
        payload = {"prompt": prompt}
        data = await self._post(self.sora2_endpoint, payload)
        task = self._parse_task(data)
        done = await self._poll_until_done(task.status_url)
        url = self._parse_done_url(done)
        if not url:
            raise CometError("Sora 2: completed but no result URL in response")
        content = await self._download(url)
        return content, "sora2.mp4"


async def sora2_image_to_video(self, prompt: str, image_b64: str, mime: str = "image/jpeg") -> Tuple[bytes, str]:
    """Image → Video (if your Comet account exposes an i2v endpoint)."""
    payload = {"prompt": prompt, "image": f"data:{mime};base64,{image_b64}"}
    data = await self._post(self.sora2_i2v_endpoint, payload)
    task = self._parse_task(data)
    done = await self._poll_until_done(task.status_url)
    url = self._parse_done_url(done)
    if not url:
        raise CometError("Sora 2 (i2v): completed but no result URL in response")
    content = await self._download(url)
    return content, "sora2_i2v.mp4"

async def kling_text_to_video(self, prompt: str) -> Tuple[bytes, str]:
    """Text → Video via Comet (Kling), if configured."""
    payload = {"prompt": prompt}
    data = await self._post(self.kling_t2v_endpoint, payload)
    task = self._parse_task(data)
    done = await self._poll_until_done(task.status_url)
    url = self._parse_done_url(done)
    if not url:
        raise CometError("Kling: completed but no result URL in response")
    content = await self._download(url)
    return content, "kling.mp4"

async def kling_image_to_video(self, prompt: str, image_b64: str, mime: str = "image/jpeg") -> Tuple[bytes, str]:
    """Image → Video via Comet (Kling), if configured."""
    payload = {"prompt": prompt, "image": f"data:{mime};base64,{image_b64}"}
    data = await self._post(self.kling_i2v_endpoint, payload)
    task = self._parse_task(data)
    done = await self._poll_until_done(task.status_url)
    url = self._parse_done_url(done)
    if not url:
        raise CometError("Kling (i2v): completed but no result URL in response")
    content = await self._download(url)
    return content, "kling_i2v.mp4"

    async def suno_text_to_music(self, prompt: str) -> Tuple[bytes, str]:
        payload = {"prompt": prompt}
        data = await self._post(self.suno_endpoint, payload)
        task = self._parse_task(data)
        done = await self._poll_until_done(task.status_url)
        url = self._parse_done_url(done)
        if not url:
            raise CometError("Suno: completed but no result URL in response")
        content = await self._download(url)
        # most common output is mp3/wav; default mp3
        return content, "suno.mp3"

    async def midjourney_imagine(self, prompt: str) -> Tuple[bytes, str]:
        payload = {"prompt": prompt}
        data = await self._post(self.mj_endpoint, payload)
        task = self._parse_task(data)
        done = await self._poll_until_done(task.status_url)
        url = self._parse_done_url(done)
        if not url:
            raise CometError("Midjourney: completed but no result URL in response")
        content = await self._download(url)
        return content, "midjourney.jpg"
