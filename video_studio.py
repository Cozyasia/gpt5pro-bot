"""Seedance 2.5 integration helpers for the Video Studio layer.

The provider exposes an asynchronous video API. This module deliberately keeps
provider-specific details outside main.py so adding or changing model aliases
does not require another secret or another bot flow.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from typing import Any, Iterable

import httpx


class SeedanceError(RuntimeError):
    """A provider or response-shape error that can be shown to the user."""


def _first_value(value: Any, keys: Iterable[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate not in (None, ""):
                return candidate
        for nested in value.values():
            found = _first_value(nested, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _first_value(nested, keys)
            if found not in (None, ""):
                return found
    return None


def _model_candidates(model: str, fallbacks: Iterable[str] | None = None) -> list[str]:
    result: list[str] = []
    for candidate in [model, *(fallbacks or ())]:
        value = str(candidate or "").strip()
        if value and value not in result:
            result.append(value)
    return result or ["seedance-2-5-260628", "seedance-2-5"]


def _size_for_aspect(aspect: str) -> str:
    normalized = str(aspect or "9:16").strip().lower()
    return {
        "9:16": "720x1280",
        "16:9": "1280x720",
        "1:1": "1024x1024",
        "4:5": "1024x1280",
    }.get(normalized, "720x1280")


def _status(payload: Any) -> str:
    value = _first_value(payload, ("status", "state", "task_status"))
    return str(value or "").strip().lower()


def _video_url(payload: Any) -> str | None:
    value = _first_value(
        payload,
        ("video_url", "download_url", "output_url", "result_url", "url"),
    )
    return str(value) if value else None


def _video_bytes(payload: Any) -> bytes | None:
    value = _first_value(payload, ("video_base64", "file_base64", "base64"))
    if not value or not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value)
    except Exception as exc:  # pragma: no cover - provider-specific fallback
        raise SeedanceError("Comet вернул некорректное base64-видео.") from exc


def _task_id(payload: Any) -> str | None:
    value = _first_value(
        payload,
        ("id", "task_id", "generation_id", "video_id", "request_id"),
    )
    return str(value) if value else None


def _is_success(status: str) -> bool:
    return status in {"completed", "complete", "succeeded", "success", "done", "finished", "ready"}


def _is_failure(status: str) -> bool:
    return status in {"failed", "failure", "error", "cancelled", "canceled", "rejected"}


async def seedance_generate(
    *,
    api_key: str,
    base_url: str,
    prompt: str,
    seconds: int,
    aspect: str = "9:16",
    model: str = "seedance-2-5-260628",
    model_fallbacks: Iterable[str] | None = None,
    reference_bytes: bytes | None = None,
    reference_name: str = "reference.jpg",
    reference_mime: str | None = None,
    create_path: str = "/v1/videos",
    timeout_s: float = 45.0,
    poll_interval_s: float = 2.5,
    max_wait_s: float = 1800.0,
) -> bytes:
    """Submit one Seedance job and return the finished mp4 bytes.

    Model aliases are tried only when the create request itself fails. Once a
    job id is returned, it is polled exactly once to avoid duplicate billing.
    """

    if not api_key:
        raise SeedanceError("Не задан COMET_API_KEY.")
    if not str(prompt or "").strip():
        raise SeedanceError("Пустой промпт для Seedance.")

    seconds = max(4, min(30, int(seconds or 10)))
    base = str(base_url or "https://api.cometapi.com").rstrip("/")
    endpoint = create_path if str(create_path).startswith("/") else f"/{create_path}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    mime = reference_mime or mimetypes.guess_type(reference_name)[0] or "image/jpeg"

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        created: Any = None
        last_error = ""
        for candidate in _model_candidates(model, model_fallbacks):
            data = {
                "model": candidate,
                "prompt": str(prompt).strip(),
                "seconds": str(seconds),
                "size": _size_for_aspect(aspect),
            }
            files = None
            if reference_bytes:
                files = {
                    "input_reference": (
                        reference_name,
                        reference_bytes,
                        mime,
                    )
                }
            try:
                response = await client.post(
                    f"{base}{endpoint}",
                    headers=headers,
                    data=data,
                    files=files,
                )
                if response.status_code >= 400:
                    last_error = f"{response.status_code}: {response.text[:500]}"
                    continue
                created = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)

        if created is None:
            raise SeedanceError(f"Не удалось запустить Seedance через Comet: {last_error}")

        immediate = _video_bytes(created)
        if immediate:
            return immediate
        immediate_url = _video_url(created)
        task_id = _task_id(created)
        if immediate_url:
            return await _download_video(client, immediate_url, headers)
        if not task_id:
            raise SeedanceError("Comet не вернул идентификатор задачи Seedance.")

        started = asyncio.get_running_loop().time()
        while True:
            if asyncio.get_running_loop().time() - started > max_wait_s:
                raise SeedanceError("Seedance не завершил задачу за отведённое время.")

            payload = None
            for status_path in (f"/v1/videos/{task_id}", f"/v1/tasks/{task_id}"):
                try:
                    response = await client.get(f"{base}{status_path}", headers=headers)
                    if response.status_code < 400:
                        payload = response.json()
                        break
                except (httpx.HTTPError, ValueError):
                    continue

            if payload is None:
                await asyncio.sleep(poll_interval_s)
                continue

            status = _status(payload)
            raw = _video_bytes(payload)
            if raw:
                return raw
            url = _video_url(payload)
            if url and (_is_success(status) or not status):
                return await _download_video(client, url, headers)
            if _is_failure(status):
                detail = _first_value(payload, ("error", "message", "detail"))
                raise SeedanceError(f"Seedance завершился с ошибкой: {detail or status}.")

            await asyncio.sleep(poll_interval_s)


async def _download_video(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
) -> bytes:
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    content = response.content
    if not content:
        raise SeedanceError("Comet вернул пустой видеофайл.")
    return content


def seedance_scene_prompt(scene: Any, base_prompt: str) -> str:
    """Turn a validated scene object into a continuity-aware prompt."""
    fields = [
        ("action", getattr(scene, "action", "")),
        ("camera", getattr(scene, "camera", "")),
        ("dialogue", getattr(scene, "dialogue", "")),
        ("sound", getattr(scene, "sound", "")),
        ("visual", getattr(scene, "visual", "")),
        ("start_state", getattr(scene, "start_state", "")),
        ("end_state", getattr(scene, "end_state", "")),
    ]
    details = "\n".join(f"{label}: {value}" for label, value in fields if value)
    return (
        f"{str(base_prompt or '').strip()}\n"
        "Create one self-contained vertical advertising scene. "
        "Keep the same character, wardrobe, props, lighting and product identity "
        "throughout the scene. Do not invent readable UI text, prices, logos or "
        "transaction values; leave any phone display clean for later compositing.\n"
        f"{details}"
    ).strip()
