from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderHTTPError(RuntimeError):
    pass


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProviderHTTPError(f"provider HTTP {exc.code}: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"provider connection failed: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderHTTPError("provider returned invalid JSON") from exc


def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    return "image/jpeg"


def _lookup(payload: Any, dotted_path: str) -> Any:
    value = payload
    for token in dotted_path.split("."):
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise KeyError(dotted_path)
    return value


@dataclass(slots=True)
class GeminiRESTTransport:
    api_key: str
    timeout_s: int = 600
    api_base: str = "https://generativelanguage.googleapis.com/v1/models"

    async def generate_image(self, *, prompt: str, references: list[bytes], model: str) -> bytes:
        if not self.api_key:
            raise ProviderHTTPError("GEMINI_API_KEY is not configured")
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts.extend(
            {
                "inline_data": {
                    "mime_type": _guess_mime(reference),
                    "data": base64.b64encode(reference).decode("ascii"),
                }
            }
            for reference in references
        )
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        response = await asyncio.to_thread(
            _post_json,
            f"{self.api_base.rstrip('/')}/{model}:generateContent",
            {"x-goog-api-key": self.api_key},
            payload,
            self.timeout_s,
        )
        for candidate in response.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"], validate=True)
        raise ProviderHTTPError("Gemini response did not contain an image")


@dataclass(slots=True)
class GenericFaceSwapRESTTransport:
    """Synchronous JSON Face Swap adapter.

    The endpoint must accept source_image and target_image as data URLs and return
    either a base64 image or an image URL at the configured dotted JSON path.
    """

    endpoint: str
    api_key: str
    timeout_s: int = 600
    result_path: str = "data.image"
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"

    async def swap(self, *, source_face: bytes, target_scene: bytes) -> bytes:
        if not self.endpoint:
            raise ProviderHTTPError("STAR_SELFIE_FACE_SWAP_URL is not configured")
        token = f"{self.auth_scheme} {self.api_key}".strip()
        headers = {self.auth_header: token} if self.api_key else {}
        payload = {
            "source_image": self._data_url(source_face),
            "target_image": self._data_url(target_scene),
            "swap_mode": "single_source_face",
        }
        response = await asyncio.to_thread(_post_json, self.endpoint, headers, payload, self.timeout_s)
        try:
            result = _lookup(response, self.result_path)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderHTTPError(f"Face Swap result path not found: {self.result_path}") from exc
        if not isinstance(result, str):
            raise ProviderHTTPError("Face Swap result is not a string")
        if result.startswith("data:"):
            _, encoded = result.split(",", 1)
            return base64.b64decode(encoded, validate=True)
        if result.startswith("http://") or result.startswith("https://"):
            return await asyncio.to_thread(self._download, result)
        return base64.b64decode(result, validate=True)

    def _download(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "GPT5Pro-StarSelfie/1.0"})
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return response.read()

    @staticmethod
    def _data_url(data: bytes) -> str:
        mime = _guess_mime(data)
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
