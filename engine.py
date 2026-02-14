# engine.py — Comet API client (Sora 2 + Kling) for GPT-5 PRO Bot
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import httpx


class CometError(RuntimeError):
    pass


def _safe_json(text: str) -> Dict[str, Any]:
    """
    Comet/Proxy can sometimes return HTML (e.g., 502/503 pages).
    Return {} for non-JSON to allow caller to decide retry vs fail.
    """
    if not text:
        return {}
    t = text.lstrip()
    if t.startswith("<"):
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _norm_base(base_url: str) -> str:
    base_url = (base_url or "").strip()
    if not base_url:
        return ""
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url


@dataclass
class CometClient:
    base_url: str
    api_key: str
    timeout: float = 180.0

    # Optional overrides for Kling
    kling_base_url: str | None = None
    kling_model_name: str = "kling-v2-6"
    kling_t2v_path: str = "videos/text2video"
    kling_i2v_path: str = "videos/image2video"
    kling_t2v_status_tpl: str = "videos/text2video/{task_id}"
    kling_i2v_status_tpl: str = "videos/image2video/{task_id}"
    kling_content_tpl: str = "videos/{task_id}/content"

    def __post_init__(self):
        self.base_url = _norm_base(self.base_url)
        if not self.base_url:
            raise CometError("COMET_BASE_URL is empty")
        self.api_key = (self.api_key or "").strip()
        if not self.api_key:
            raise CometError("COMETAPI_KEY is empty")

        # env overrides
        self.kling_base_url = (self.kling_base_url or os.environ.get("COMET_KLING_BASE_URL") or "").strip() or None
        self.kling_model_name = (os.environ.get("COMET_KLING_MODEL_NAME") or self.kling_model_name).strip()
        self.kling_t2v_path = (os.environ.get("COMET_KLING_T2V_PATH") or self.kling_t2v_path).strip().lstrip("/")
        self.kling_i2v_path = (os.environ.get("COMET_KLING_I2V_PATH") or self.kling_i2v_path).strip().lstrip("/")
        self.kling_t2v_status_tpl = (os.environ.get("COMET_KLING_T2V_STATUS_TPL") or self.kling_t2v_status_tpl).strip().lstrip("/")
        self.kling_i2v_status_tpl = (os.environ.get("COMET_KLING_I2V_STATUS_TPL") or self.kling_i2v_status_tpl).strip().lstrip("/")
        self.kling_content_tpl = (os.environ.get("COMET_KLING_CONTENT_TPL") or self.kling_content_tpl).strip().lstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)

    # -------------------- Sora 2 (Comet /v1/videos) --------------------
    async def sora2_text_to_video(self, prompt: str) -> Tuple[bytes, str]:
        return await self._sora2_submit_and_get(prompt=prompt, image_b64=None, mime=None)

    async def sora2_image_to_video(self, prompt: str, image_b64: str, mime: str = "image/jpeg") -> Tuple[bytes, str]:
        return await self._sora2_submit_and_get(prompt=prompt, image_b64=image_b64, mime=mime)

    async def _sora2_submit_and_get(self, prompt: str, image_b64: Optional[str], mime: Optional[str]) -> Tuple[bytes, str]:
        """
        Endpoint (docs provided by user):
          POST https://api.cometapi.com/v1/videos (multipart form)
            model=sora-2
            prompt=...
            (optional image= data:<mime>;base64,<b64>  OR file bytes depending on deployment)
          GET  https://api.cometapi.com/v1/videos/{id}
          GET  https://api.cometapi.com/v1/videos/{id}/content
        """
        base = self.base_url
        submit_url = urljoin(base, "v1/videos")
        async with await self._client() as c:
            files = {
                "model": (None, "sora-2"),
                "prompt": (None, (prompt or "").strip() or "Generate a short cinematic clip."),
            }
            if image_b64:
                # Use data-URI in a form field for maximum compatibility with proxy implementations.
                data_uri = f"data:{mime or 'image/jpeg'};base64,{image_b64}"
                files["image"] = (None, data_uri)

            r = await c.post(submit_url, headers=self._headers(), files=files)
            txt = r.text or ""
            data = _safe_json(txt)
            if r.status_code >= 400 or not data:
                raise CometError(f"Comet submit returned non-JSON or error: HTTP {r.status_code} {txt[:400]}")
            vid = data.get("id") or (data.get("data") or {}).get("id")
            if not vid:
                raise CometError(f"Comet submit: missing id. Response: {txt[:600]}")

            # poll
            status_url = urljoin(base, f"v1/videos/{vid}")
            for _ in range(int(self.timeout // 5) + 1):
                s = await c.get(status_url, headers=self._headers())
                stxt = s.text or ""
                sdata = _safe_json(stxt)
                if not sdata:
                    await asyncio.sleep(5)
                    continue

                data_obj = sdata.get("data") or sdata
                progress = (data_obj.get("progress") or "0%").strip()
                status = (data_obj.get("status") or data_obj.get("state") or "unknown").strip()

                if str(status).lower() in ("failure", "failed", "error"):
                    raise CometError(f"Sora 2 failed: {stxt[:800]}")

                if progress == "100%" or str(status).lower() in ("success", "succeeded", "completed", "done"):
                    break

                await asyncio.sleep(5)

            # download
            content_url = urljoin(base, f"v1/videos/{vid}/content")
            v = await c.get(content_url, headers=self._headers())
            if v.status_code >= 400 or not v.content:
                raise CometError(f"Sora 2 content download failed: HTTP {v.status_code} {(v.text or '')[:400]}")
            return v.content, f"sora-2_{vid}.mp4"

    # -------------------- Kling (Comet /kling/v1) --------------------
    def _kling_base(self) -> str:
        if self.kling_base_url:
            return _norm_base(self.kling_base_url)
        # default: <base>/kling/v1
        return urljoin(self.base_url, "kling/v1/")

    async def kling_text_to_video(self, prompt: str) -> Tuple[bytes, str]:
        task_id = await self._kling_create_task(prompt=prompt, image_b64=None, mime=None, is_i2v=False)
        return await self._kling_wait_and_download(task_id, is_i2v=False)

    async def kling_image_to_video(self, prompt: str, image_b64: str, mime: str = "image/jpeg") -> Tuple[bytes, str]:
        # Not all deployments support image2video. We try and return a clear error if unsupported.
        task_id = await self._kling_create_task(prompt=prompt, image_b64=image_b64, mime=mime, is_i2v=True)
        return await self._kling_wait_and_download(task_id, is_i2v=True)

    async def _kling_create_task(self, prompt: str, image_b64: Optional[str], mime: Optional[str], is_i2v: bool) -> str:
        base = self._kling_base()
        path = self.kling_i2v_path if is_i2v else self.kling_t2v_path
        url = urljoin(base, path.lstrip("/"))

        prompt_txt = (prompt or "").strip() or "A short cinematic clip."

        async with await self._client() as c:
            # Kling image2video на некоторых прокси требует загрузку ФАЙЛА (jpg/jpeg/png),
            # а не data:URI. Поэтому для i2v используем multipart с корректным filename/mime.
            if is_i2v and image_b64:
                # decode b64 (accept raw b64 or data-uri)
                b = image_b64
                if "base64," in b:
                    b = b.split("base64,", 1)[1]
                try:
                    img_bytes = __import__("base64").b64decode(b)
                except Exception:
                    raise CometError("Kling i2v: invalid base64 image")
                mm = (mime or "image/jpeg").lower().strip()
                ext = "jpg"
                if "png" in mm:
                    ext = "png"
                filename = f"image.{ext}"
                files = {
                    "prompt": (None, prompt_txt),
                    "model_name": (None, self.kling_model_name),
                    "image": (filename, img_bytes, mm),
                }
                r = await c.post(url, headers=self._headers(), files=files)
            else:
                payload: Dict[str, Any] = {
                    "prompt": prompt_txt,
                    "model_name": self.kling_model_name,
                }
                r = await c.post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=payload)

            txt = r.text or ""
            data = _safe_json(txt)
            if r.status_code >= 400 or not data:
                raise CometError(f"Kling submit returned non-JSON or error: HTTP {r.status_code} {txt[:400]}")
            task_id = (data.get("data") or {}).get("task_id") or data.get("task_id") or data.get("id")
            if not task_id:
                raise CometError(f"Kling submit: missing task_id. Response: {txt[:600]}")
            return task_id

    async def _kling_wait_and_download(self, task_id: str, is_i2v: bool) -> Tuple[bytes, str]:
        base = self._kling_base()
        status_path = (self.kling_i2v_status_tpl if is_i2v else self.kling_t2v_status_tpl).format(task_id=task_id)
        status_url = urljoin(base, status_path.lstrip("/"))

        async with await self._client() as c:
            last_txt = ""
            for _ in range(int(self.timeout // 5) + 1):
                r = await c.get(status_url, headers=self._headers())
                last_txt = r.text or ""
                data = _safe_json(last_txt)
                if not data:
                    await asyncio.sleep(5)
                    continue
                d = data.get("data") or data
                status = (d.get("status") or d.get("task_status") or "").lower().strip()
                if status in ("failure", "failed", "error"):
                    raise CometError(f"Kling failed: {last_txt[:900]}")
                if status in ("success", "succeeded", "completed", "done") or d.get("video_url") or d.get("url"):
                    break
                await asyncio.sleep(5)

            # Try find direct URL first
            d = (_safe_json(last_txt).get("data") or _safe_json(last_txt)) if last_txt else {}
            url = (d.get("video_url") or d.get("url") or (d.get("result") or {}).get("video_url") or "").strip()
            if url:
                v = await c.get(url, headers=self._headers())
                if v.status_code < 400 and v.content:
                    return v.content, f"kling_{task_id}.mp4"

            # Fallback to generic /content template (if provided)
            content_url = urljoin(base, self.kling_content_tpl.format(task_id=task_id).lstrip("/"))
            v = await c.get(content_url, headers=self._headers())
            if v.status_code >= 400 or not v.content:
                raise CometError(f"Kling content download failed: HTTP {v.status_code} {(v.text or '')[:400]}")
            return v.content, f"kling_{task_id}.mp4"
