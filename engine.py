# -*- coding: utf-8 -*-
"""CometAPI helpers (Sora 2 / Kling / Midjourney / Suno)

This module is intentionally small and defensive:
- Normalizes Comet endpoints and task polling
- Provides a single CometClient used by main.py

Env:
  COMET_API_KEY                 required for all Comet calls
  COMET_BASE_URL                default: https://api.cometapi.com
  COMET_TASK_PATH               default: /v1/tasks

  COMET_SORA2_ENDPOINT          default: /v1/sora/video
  COMET_SORA2_I2V_ENDPOINT      default: /v1/sora/image-to-video

  COMET_KLING_ENDPOINT          default: /v1/kling/video
  COMET_KLING_I2V_ENDPOINT      default: /v1/kling/image-to-video

  COMET_MJ_ENDPOINT             default: /v1/midjourney/imagine
  COMET_SUNO_ENDPOINT           default: /v1/suno/music

Notes:
- Different providers sometimes return slightly different JSON shapes.
  We accept: id / task_id / data.id / result.url / output.url, etc.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx


class CometError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def _pick(d: Dict[str, Any], *keys: str) -> Optional[Any]:
    """Pick first existing key (supports dotted keys like 'data.id')."""
    for k in keys:
        cur: Any = d
        ok = True
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


class CometClient:
    def __init__(self) -> None:
        self.api_key = _env("COMET_API_KEY")
        self.base_url = _env("COMET_BASE_URL", "https://api.cometapi.com").rstrip("/")
        self.task_path = _env("COMET_TASK_PATH", "/v1/tasks").rstrip("/")

        self.sora2_endpoint = _env("COMET_SORA2_ENDPOINT", "/v1/sora/video")
        self.sora2_i2v_endpoint = _env("COMET_SORA2_I2V_ENDPOINT", "/v1/sora/image-to-video")

        self.kling_endpoint = _env("COMET_KLING_ENDPOINT", "/v1/kling/video")
        self.kling_i2v_endpoint = _env("COMET_KLING_I2V_ENDPOINT", "/v1/kling/image-to-video")

        self.mj_endpoint = _env("COMET_MJ_ENDPOINT", "/v1/midjourney/imagine")
        self.suno_endpoint = _env("COMET_SUNO_ENDPOINT", "/v1/suno/music")

        self.timeout = float(_env("COMET_TIMEOUT", "60")) if _env("COMET_TIMEOUT", "") else 60.0

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        # CometAPI generally uses Bearer token.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    async def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled():
            raise CometError("COMET_API_KEY is not set")
        url = self._url(path)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
        if r.status_code >= 400:
            raise CometError(f"HTTP {r.status_code} on POST {path}: {r.text[:500]}")
        try:
            return r.json()
        except Exception:
            raise CometError(f"Invalid JSON on POST {path}: {r.text[:500]}") from None

    async def _get_json(self, path: str) -> Dict[str, Any]:
        if not self.enabled():
            raise CometError("COMET_API_KEY is not set")
        url = self._url(path)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, headers=self._headers())
        if r.status_code >= 400:
            raise CometError(f"HTTP {r.status_code} on GET {path}: {r.text[:500]}")
        try:
            return r.json()
        except Exception:
            raise CometError(f"Invalid JSON on GET {path}: {r.text[:500]}") from None

    def _extract_task_id(self, resp: Dict[str, Any]) -> str:
        task_id = _pick(resp, "id", "task_id", "data.id", "data.task_id", "result.id")
        if not task_id:
            raise CometError(f"Cannot find task id in response: {str(resp)[:500]}")
        return str(task_id)

    def _extract_video_url(self, resp: Dict[str, Any]) -> Optional[str]:
        url = _pick(
            resp,
            "result.url",
            "result.video_url",
            "result.output_url",
            "output.url",
            "output.video_url",
            "data.url",
            "data.output.url",
            "data.output_url",
        )
        if isinstance(url, str) and url.startswith("http"):
            return url
        # Sometimes: outputs: [{url: ...}]
        outputs = _pick(resp, "outputs", "result.outputs", "data.outputs")
        if isinstance(outputs, list) and outputs:
            for item in outputs:
                if isinstance(item, dict):
                    u = item.get("url") or item.get("video_url") or item.get("output_url")
                    if isinstance(u, str) and u.startswith("http"):
                        return u
        return None

    def _task_status(self, resp: Dict[str, Any]) -> str:
        st = _pick(resp, "status", "data.status", "result.status") or ""
        return str(st).lower()

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        # Comet tasks are typically: GET /v1/tasks/{id}
        if task_id.startswith("http://") or task_id.startswith("https://"):
            # If full URL is returned, just use it.
            path = task_id
            return await self._get_json(path)
        return await self._get_json(f"{self.task_path}/{task_id}")

    async def wait_for_video(self, task_id: str, timeout_s: int = 240, poll_s: int = 4) -> str:
        t0 = time.time()
        last = None
        while True:
            resp = await self.get_task(task_id)
            last = resp
            st = self._task_status(resp)
            if st in ("succeeded", "success", "completed", "done", "finished"):
                url = self._extract_video_url(resp)
                if not url:
                    raise CometError(f"Task succeeded but no video url: {str(resp)[:700]}")
                return url
            if st in ("failed", "error", "canceled", "cancelled"):
                raise CometError(f"Task failed ({st}): {str(resp)[:700]}")
            if time.time() - t0 > timeout_s:
                raise CometError(f"Timeout waiting for task {task_id}. Last: {str(last)[:700]}")
            time.sleep(poll_s)

    # ---------- Sora 2 ----------
    async def sora2_text_to_video(
        self,
        prompt: str,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> str:
        payload = {
            "prompt": prompt,
            "duration": int(duration_s),
            "aspect_ratio": aspect_ratio,
        }
        resp = await self._post_json(self.sora2_endpoint, payload)
        return self._extract_task_id(resp)

    async def sora2_image_to_video(
        self,
        image_b64: str,
        prompt: str = "",
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> str:
        payload = {
            "image": image_b64,
            "prompt": prompt or "",
            "duration": int(duration_s),
            "aspect_ratio": aspect_ratio,
        }
        resp = await self._post_json(self.sora2_i2v_endpoint, payload)
        return self._extract_task_id(resp)

    # ---------- Kling ----------
    async def kling_text_to_video(
        self,
        prompt: str,
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> str:
        payload = {
            "prompt": prompt,
            "duration": int(duration_s),
            "aspect_ratio": aspect_ratio,
        }
        resp = await self._post_json(self.kling_endpoint, payload)
        return self._extract_task_id(resp)

    async def kling_image_to_video(
        self,
        image_b64: str,
        prompt: str = "",
        duration_s: int = 5,
        aspect_ratio: str = "16:9",
    ) -> str:
        payload = {
            "image": image_b64,
            "prompt": prompt or "",
            "duration": int(duration_s),
            "aspect_ratio": aspect_ratio,
        }
        resp = await self._post_json(self.kling_i2v_endpoint, payload)
        return self._extract_task_id(resp)

    # ---------- Midjourney ----------
    async def midjourney_imagine(self, prompt: str) -> str:
        payload = {"prompt": prompt}
        resp = await self._post_json(self.mj_endpoint, payload)
        return self._extract_task_id(resp)

    # ---------- Suno ----------
    async def suno_text_to_music(self, prompt: str, duration_s: int = 30) -> str:
        payload = {"prompt": prompt, "duration": int(duration_s)}
        resp = await self._post_json(self.suno_endpoint, payload)
        return self._extract_task_id(resp)
