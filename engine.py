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

    async def _get(self, url: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, headers=self._headers())
            txt = (r.text or "")[:2000]
            if r.status_code >= 400:
                raise CometError(f"HTTP {r.status_code} from Comet status: {txt}")
            try:
                return r.json()
            except Exception:
                raise CometError(f"Comet status returned non-JSON: {txt}")

    def _status_url(self, task_id: str) -> str:
        path = self.status_tmpl.format(id=task_id)
        return _join(self.base_url, path)

    def _parse_task(self, d: Dict[str, Any]) -> TaskInfo:
        task_id = d.get("id") or d.get("task_id") or d.get("taskId")
        if not task_id:
            raise CometError(f"Comet did not return task id. Keys: {list(d.keys())}")
        return TaskInfo(task_id=str(task_id), status_url=self._status_url(str(task_id)))

    def _extract_result_url(self, d: Dict[str, Any]) -> Optional[str]:
        # direct fields
        direct = _first(d, self.result_fields)
        if isinstance(direct, str) and direct.startswith(("http://", "https://")):
            return direct

        # nested common containers
        for container_key in ("result", "output", "data", "asset", "assets"):
            obj = d.get(container_key)
            if isinstance(obj, dict):
                direct2 = _first(obj, self.result_fields)
                if isinstance(direct2, str) and direct2.startswith(("http://", "https://")):
                    return direct2
            if isinstance(obj, list) and obj:
                first = obj[0]
                if isinstance(first, dict):
                    direct3 = _first(first, self.result_fields)
                    if isinstance(direct3, str) and direct3.startswith(("http://", "https://")):
                        return direct3

        return None

    async def submit_sora2_text_to_video(self, prompt: str, **kwargs) -> TaskInfo:
        payload = {"prompt": prompt}
        payload.update(kwargs or {})
        d = await self._post(self.sora2_endpoint, payload)
        return self._parse_task(d)

    async def submit_sora2_image_to_video(self, image_url: str, prompt: str = "", **kwargs) -> TaskInfo:
        payload = {"image": image_url, "prompt": prompt}
        payload.update(kwargs or {})
        d = await self._post(self.sora2_i2v_endpoint, payload)
        return self._parse_task(d)

    async def submit_kling_text_to_video(self, prompt: str, **kwargs) -> TaskInfo:
        payload = {"prompt": prompt}
        payload.update(kwargs or {})
        d = await self._post(self.kling_t2v_endpoint, payload)
        return self._parse_task(d)

    async def submit_kling_image_to_video(self, image_url: str, prompt: str = "", **kwargs) -> TaskInfo:
        payload = {"image": image_url, "prompt": prompt}
        payload.update(kwargs or {})
        d = await self._post(self.kling_i2v_endpoint, payload)
        return self._parse_task(d)

    async def submit_suno_text_to_music(self, prompt: str, **kwargs) -> TaskInfo:
        payload = {"prompt": prompt}
        payload.update(kwargs or {})
        d = await self._post(self.suno_endpoint, payload)
        return self._parse_task(d)

    async def submit_midjourney_imagine(self, prompt: str, **kwargs) -> TaskInfo:
        payload = {"prompt": prompt}
        payload.update(kwargs or {})
        d = await self._post(self.mj_endpoint, payload)
        return self._parse_task(d)

    async def wait_result_url(
        self,
        task: TaskInfo,
        poll_interval: float = 5.0,
        timeout_s: float = 900.0,
    ) -> Tuple[str, Dict[str, Any]]:
        deadline = time.time() + timeout_s
        last_status = None

        while time.time() < deadline:
            d = await self._get(task.status_url)

            status = (d.get("status") or d.get("state") or "").lower().strip()
            if status and status != last_status:
                last_status = status

            url = self._extract_result_url(d)
            if url:
                return url, d

            if status in ("failed", "error", "canceled", "cancelled"):
                raise CometError(f"Comet task failed: {json.dumps(d, ensure_ascii=False)[:2000]}")

            await asyncio.sleep(poll_interval)

        raise CometError("Timeout while waiting Comet result")
