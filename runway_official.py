# -*- coding: utf-8 -*-
"""Official Runway Developer API client for Neyro-Bot.

Implements the documented REST flow without exposing the API secret:
- POST /v1/text_to_video
- POST /v1/image_to_video
- GET  /v1/tasks/{id}
- GET  /v1/organization
- POST /v1/uploads + presigned multipart upload

The client intentionally has no Telegram or billing dependencies.
"""
from __future__ import annotations

import asyncio
import base64
import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

import httpx

from secret_loader import bootstrap_secret_environment, get_secret
bootstrap_secret_environment()


RETRYABLE_HTTP = {429, 502, 503, 504}
TERMINAL_SUCCESS = {"SUCCEEDED"}
TERMINAL_FAILURE = {"FAILED", "CANCELED", "CANCELLED"}
ACTIVE_STATUSES = {"PENDING", "RUNNING", "THROTTLED"}


class RunwayAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
        retryable: bool = False,
        failure_code: str = "",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.retryable = retryable
        self.failure_code = failure_code


class RunwayTaskTimeout(RunwayAPIError):
    pass


@dataclass(slots=True)
class RunwayTaskResult:
    id: str
    status: str
    output: list[str]
    raw: dict[str, Any]

    @property
    def first_output(self) -> str:
        return self.output[0] if self.output else ""


def normalize_base_url(base_url: str) -> str:
    base = (base_url or "https://api.dev.runwayml.com").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    return base or "https://api.dev.runwayml.com"


def key_format_hint(api_key: str) -> tuple[bool, str]:
    """Non-blocking key format check based on current Runway documentation."""
    key = (api_key or "").strip()
    if not key:
        return False, "ключ отсутствует"
    if re.fullmatch(r"key_[0-9a-fA-F]{128}", key):
        return True, "формат ключа корректный"
    if key.startswith("key_") and len(key) >= 64:
        return True, "ключ начинается с key_; окончательную проверку выполнит API"
    return False, "ключ имеет необычный формат: ожидается key_…"


def safe_key_fingerprint(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return "—"
    return f"{key[:4]}…{key[-4:]} ({len(key)} симв.)"


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return (response.text or "").strip()


def _error_text(payload: Any, status_code: int | None = None) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            text = err.get("message") or err.get("detail") or err.get("code")
            if text:
                return str(text)
        for key in ("message", "detail", "failure", "failureCode", "code"):
            if payload.get(key):
                return str(payload[key])
        return json.dumps(payload, ensure_ascii=False)[:1200]
    text = str(payload or "").strip()
    return text[:1200] or (f"HTTP {status_code}" if status_code else "Runway API error")


def _extract_output_urls(data: Any) -> list[str]:
    urls: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, str):
            if obj.startswith(("https://", "http://")) and obj not in urls:
                urls.append(obj)
            return
        if isinstance(obj, dict):
            # Prefer documented output first.
            if "output" in obj:
                walk(obj.get("output"))
            for key, value in obj.items():
                if key == "output":
                    continue
                if key.lower() in {"url", "video", "videourl", "video_url", "downloadurl", "download_url"}:
                    walk(value)
            return
        if isinstance(obj, (list, tuple)):
            for item in obj:
                walk(item)

    walk(data)
    return urls


class RunwayOfficialClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.dev.runwayml.com",
        api_version: str = "2024-11-06",
        retry_attempts: int = 4,
        retry_base_s: float = 1.5,
        poll_interval_s: float = 5.0,
        poll_max_interval_s: float = 15.0,
        timeout_s: float = 90.0,
        upload_attempts: int = 2,
        data_uri_fallback: bool = True,
    ):
        resolved_key = (api_key or "").strip()
        if not resolved_key:
            resolved_key, _ = get_secret("RUNWAYML_API_SECRET", "RUNWAY_API_KEY", "RUNWAY_KEY")
        self.api_key = resolved_key
        if not self.api_key:
            raise RunwayAPIError("RUNWAYML_API_SECRET is not configured in Environment or Secret Files")
        self.base_url = normalize_base_url(base_url)
        self.api_version = (api_version or "2024-11-06").strip()
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_base_s = max(0.5, float(retry_base_s))
        self.poll_interval_s = max(5.0, float(poll_interval_s))
        self.poll_max_interval_s = max(self.poll_interval_s, float(poll_max_interval_s))
        self.upload_attempts = max(1, int(upload_attempts))
        self.data_uri_fallback = bool(data_uri_fallback)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False)

    async def __aenter__(self) -> "RunwayOfficialClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def headers(self, *, json_content: bool = True) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Runway-Version": self.api_version,
            "User-Agent": "Neyro-Bot-GPT5-Studio/1.0",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        attempts = self.retry_attempts if retry else 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=self.headers(),
                    json=json_body,
                )
                if response.status_code not in RETRYABLE_HTTP or attempt >= attempts - 1:
                    return response
                retry_after = response.headers.get("retry-after", "").strip()
                try:
                    delay = max(float(retry_after), self.retry_base_s * (2**attempt)) if retry_after else self.retry_base_s * (2**attempt)
                except Exception:
                    delay = self.retry_base_s * (2**attempt)
                delay += random.uniform(0, max(0.2, delay * 0.35))
                await asyncio.sleep(delay)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise RunwayAPIError(
                        f"Runway transport error: {exc}", retryable=True
                    ) from exc
                delay = self.retry_base_s * (2**attempt)
                delay += random.uniform(0, max(0.2, delay * 0.35))
                await asyncio.sleep(delay)

        if last_exc:
            raise RunwayAPIError(str(last_exc), retryable=True) from last_exc
        raise RunwayAPIError("Runway request failed")

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        payload = _json_or_text(response)
        message = _error_text(payload, response.status_code)
        failure_code = ""
        if isinstance(payload, dict):
            failure_code = str(payload.get("failureCode") or payload.get("code") or "")
        raise RunwayAPIError(
            f"HTTP {response.status_code}: {message}",
            status_code=response.status_code,
            payload=payload,
            retryable=response.status_code in RETRYABLE_HTTP,
            failure_code=failure_code,
        )

    async def organization(self, *, endpoint: str = "/v1/organization") -> dict[str, Any]:
        response = await self._request("GET", endpoint)
        self._raise_for_error(response)
        data = _json_or_text(response)
        return data if isinstance(data, dict) else {"raw": data}

    async def create_text_to_video(
        self,
        *,
        prompt_text: str,
        model: str = "gen4.5",
        ratio: str = "1280:720",
        duration: int = 5,
        endpoint: str = "/v1/text_to_video",
        compatibility_endpoint: str = "/v1/image_to_video",
    ) -> str:
        payload = {
            "model": model,
            "promptText": (prompt_text or "").strip()[:4000],
            "ratio": ratio,
            "duration": max(2, min(10, int(duration))),
        }
        if not payload["promptText"]:
            raise RunwayAPIError("Runway text-to-video prompt is empty")

        response = await self._request("POST", endpoint, json_body=payload)
        # Current API reference exposes /v1/text_to_video. The compatibility
        # path preserves support for deployments still using the older guide.
        if response.status_code in {404, 405} and compatibility_endpoint:
            response = await self._request("POST", compatibility_endpoint, json_body=payload)
        self._raise_for_error(response)
        data = _json_or_text(response)
        task_id = str((data or {}).get("id") or (data or {}).get("taskId") or "") if isinstance(data, dict) else ""
        if not task_id:
            raise RunwayAPIError(f"Runway did not return a task id: {str(data)[:800]}")
        return task_id

    async def upload_ephemeral(
        self,
        *,
        content: bytes,
        filename: str,
        mime_type: str,
        endpoint: str = "/v1/uploads",
    ) -> str:
        if not content:
            raise RunwayAPIError("Runway upload content is empty")
        if len(content) < 512:
            raise RunwayAPIError("Runway upload is smaller than the 512-byte minimum")
        if len(content) > 200 * 1024 * 1024:
            raise RunwayAPIError("Runway upload exceeds the 200MB limit")

        last_error = ""
        for _ in range(self.upload_attempts):
            # A failed presigned upload must not be retried with the same slot.
            # Each loop creates a brand-new upload slot as required by the docs.
            slot_response = await self._request(
                "POST",
                endpoint,
                json_body={"filename": filename, "type": "ephemeral"},
            )
            self._raise_for_error(slot_response)
            slot = _json_or_text(slot_response)
            if not isinstance(slot, dict):
                raise RunwayAPIError(f"Unexpected upload slot response: {slot}")
            upload_url = str(slot.get("uploadUrl") or "")
            runway_uri = str(slot.get("runwayUri") or slot.get("uri") or "")
            fields = slot.get("fields") or {}
            if not upload_url or not runway_uri or not isinstance(fields, dict):
                raise RunwayAPIError(f"Incomplete upload slot response: {json.dumps(slot, ensure_ascii=False)[:900]}")

            try:
                upload_response = await self._client.post(
                    upload_url,
                    data={str(k): str(v) for k, v in fields.items()},
                    files={"file": (filename, content, mime_type)},
                    headers={"User-Agent": "Neyro-Bot-GPT5-Studio/1.0"},
                    timeout=180.0,
                    follow_redirects=False,
                )
                if upload_response.status_code in {200, 201, 204}:
                    return runway_uri
                last_error = f"upload HTTP {upload_response.status_code}: {(upload_response.text or '')[:500]}"
            except Exception as exc:
                last_error = str(exc)

        raise RunwayAPIError(f"Runway ephemeral upload failed: {last_error}")

    async def create_image_to_video(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        mime_type: str,
        prompt_text: str,
        model: str = "gen4.5",
        ratio: str = "1280:720",
        duration: int = 5,
        endpoint: str = "/v1/image_to_video",
        upload_endpoint: str = "/v1/uploads",
    ) -> str:
        try:
            image_ref = await self.upload_ephemeral(
                content=image_bytes,
                filename=filename,
                mime_type=mime_type,
                endpoint=upload_endpoint,
            )
        except RunwayAPIError:
            if not self.data_uri_fallback or len(image_bytes) > 5 * 1024 * 1024:
                raise
            encoded = base64.b64encode(image_bytes).decode("ascii")
            image_ref = f"data:{mime_type};base64,{encoded}"

        payload = {
            "model": model,
            "promptImage": image_ref,
            "promptText": (prompt_text or "").strip()[:4000],
            "ratio": ratio,
            "duration": max(2, min(10, int(duration))),
        }
        response = await self._request("POST", endpoint, json_body=payload)
        self._raise_for_error(response)
        data = _json_or_text(response)
        task_id = str((data or {}).get("id") or (data or {}).get("taskId") or "") if isinstance(data, dict) else ""
        if not task_id:
            raise RunwayAPIError(f"Runway did not return a task id: {str(data)[:800]}")
        return task_id

    async def retrieve_task(self, task_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/v1/tasks/{task_id}")
        self._raise_for_error(response)
        data = _json_or_text(response)
        return data if isinstance(data, dict) else {"raw": data}

    async def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_s: float = 900.0,
        on_status: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> RunwayTaskResult:
        started = time.monotonic()
        interval = self.poll_interval_s
        last_status = ""

        while True:
            if time.monotonic() - started > timeout_s:
                raise RunwayTaskTimeout(
                    f"Runway task {task_id} timed out after {int(timeout_s)} seconds",
                    retryable=False,
                )

            data = await self.retrieve_task(task_id)
            status = str(data.get("status") or "").upper()
            if on_status and status != last_status:
                maybe = on_status(status, data)
                if asyncio.iscoroutine(maybe):
                    await maybe
            last_status = status

            if status in TERMINAL_SUCCESS:
                urls = _extract_output_urls(data.get("output") or data)
                if not urls:
                    raise RunwayAPIError(
                        f"Runway task succeeded without output URLs: {json.dumps(data, ensure_ascii=False)[:1000]}"
                    )
                return RunwayTaskResult(task_id, status, urls, data)

            if status in TERMINAL_FAILURE:
                failure_code = str(data.get("failureCode") or "")
                failure = data.get("failure") or data.get("error") or failure_code or "task failed"
                raise RunwayAPIError(
                    f"Runway task {status}: {failure}",
                    payload=data,
                    failure_code=failure_code,
                )

            # Unknown statuses are treated as active for forward compatibility.
            delay = interval + random.uniform(0.0, min(1.5, interval * 0.2))
            await asyncio.sleep(delay)
            interval = min(self.poll_max_interval_s, interval * 1.15)
