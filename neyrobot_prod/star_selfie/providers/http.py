from __future__ import annotations

import asyncio
import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from typing import Any


class ProviderHTTPError(RuntimeError):
    pass


def _request(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProviderHTTPError(f"provider HTTP {exc.code}: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"provider connection failed: {exc.reason}") from exc


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    raw, _ = _request(url, headers, payload, timeout)
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


def _is_image(data: bytes) -> bool:
    return data.startswith((b"\xff\xd8\xff", b"\x89PNG")) or (
        data.startswith(b"RIFF") and b"WEBP" in data[:16]
    )


def _normalize_jpeg(data: bytes, *, max_side: int = 2048) -> bytes:
    try:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((max_side, max_side))
            output = BytesIO()
            image.save(output, format="JPEG", quality=95, optimize=True)
            normalized = output.getvalue()
            if not normalized.startswith(b"\xff\xd8\xff"):
                raise ValueError("JPEG encoder returned invalid data")
            return normalized
    except Exception as exc:
        raise ProviderHTTPError(f"invalid input image: {type(exc).__name__}: {exc}") from exc


def _decode_image_value(value: Any) -> bytes:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict):
        for key in ("image", "url", "output"):
            if key in value:
                return _decode_image_value(value[key])
    if not isinstance(value, str):
        raise ProviderHTTPError("provider image result is not a string")
    if value.startswith("data:"):
        _, encoded = value.split(",", 1)
        return base64.b64decode(encoded, validate=True)
    if value.startswith("http://") or value.startswith("https://"):
        request = urllib.request.Request(value, headers={"User-Agent": "GPT5Pro-StarSelfie/1.0"})
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.read()
    return base64.b64decode(value, validate=True)


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
            raise ProviderHTTPError("Gemini image API key is not configured")
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
class SegmindFaceSwapRESTTransport:
    endpoint: str
    api_key: str
    timeout_s: int = 600
    face_restore: str = "codeformer-v0.1.0.pth"

    async def swap(self, *, source_face: bytes, target_scene: bytes) -> bytes:
        if not self.endpoint:
            raise ProviderHTTPError("Segmind FaceSwap URL is not configured")
        if not self.api_key:
            raise ProviderHTTPError("SEGMIND_API_KEY is not configured")
        source_jpeg = await asyncio.to_thread(_normalize_jpeg, source_face)
        target_jpeg = await asyncio.to_thread(_normalize_jpeg, target_scene)
        payload = {
            "source_img": base64.b64encode(source_jpeg).decode("ascii"),
            "target_img": base64.b64encode(target_jpeg).decode("ascii"),
            "input_faces_index": "0",
            "source_faces_index": "0",
            "face_restore": self.face_restore,
            "base64": False,
        }
        raw, content_type = await asyncio.to_thread(
            _request,
            self.endpoint,
            {"x-api-key": self.api_key, "Accept": "image/*, application/json"},
            payload,
            self.timeout_s,
        )
        if content_type.lower().startswith("image/") or _is_image(raw):
            return raw
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderHTTPError("Segmind returned neither an image nor valid JSON") from exc
        for key in ("output", "image", "data"):
            if key in response:
                return _decode_image_value(response[key])
        raise ProviderHTTPError("Segmind response did not contain an image")


@dataclass(slots=True)
class GenericFaceSwapRESTTransport:
    """Synchronous JSON Face Swap adapter for custom providers."""

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
        return _decode_image_value(result)

    @staticmethod
    def _data_url(data: bytes) -> str:
        return f"data:{_guess_mime(data)};base64,{base64.b64encode(data).decode('ascii')}"
