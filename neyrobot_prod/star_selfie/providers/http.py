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
        raise ProviderHTTPError(f"provider HTTP {exc.code}: {body[:1500]}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"provider connection failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ProviderHTTPError(f"provider timed out after {timeout}s") from exc


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
            image.save(output, format="JPEG", quality=97, optimize=True, subsampling=0)
            normalized = output.getvalue()
            if not normalized.startswith(b"\xff\xd8\xff"):
                raise ValueError("JPEG encoder returned invalid data")
            return normalized
    except Exception as exc:
        raise ProviderHTTPError(f"invalid input image: {type(exc).__name__}: {exc}") from exc


def _decode_image_value(value: Any) -> bytes:
    if isinstance(value, list) and value:
        value = value[-1]
    if isinstance(value, dict):
        for key in ("data", "image", "output_image", "output", "url"):
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


def _interactions_url(api_base: str) -> str:
    base = (api_base or "").strip().rstrip("/")
    if base.endswith("/interactions"):
        return base
    if "/v1/models" in base or "/v1beta/models" in base:
        root = base.split("/v1", 1)[0]
        return f"{root}/v1beta/interactions"
    if base:
        return f"{base}/v1beta/interactions"
    return "https://generativelanguage.googleapis.com/v1beta/interactions"


def _extract_interaction_image(response: dict[str, Any]) -> bytes:
    direct = response.get("output_image") or response.get("outputImage")
    if direct:
        image = _decode_image_value(direct)
        if _is_image(image):
            return image

    found: list[bytes] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            block_type = str(value.get("type") or "").lower()
            if block_type in {"image", "output_image"} and value.get("data"):
                try:
                    decoded = base64.b64decode(str(value["data"]), validate=True)
                    if _is_image(decoded):
                        found.append(decoded)
                except Exception:
                    pass
            for key, nested in value.items():
                if key in {"thought", "thinking"} and nested is True:
                    continue
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(response.get("output"))
    walk(response.get("steps"))
    if found:
        return found[-1]
    raise ProviderHTTPError(
        "Gemini interaction did not contain output_image; response keys="
        + ",".join(sorted(response.keys()))
    )


@dataclass(slots=True)
class GeminiRESTTransport:
    api_key: str
    timeout_s: int = 600
    api_base: str = "https://generativelanguage.googleapis.com/v1beta/interactions"

    async def generate_image(
        self,
        *,
        prompt: str,
        references: list[bytes],
        model: str,
        reference_labels: list[str] | None = None,
    ) -> bytes:
        if not self.api_key:
            raise ProviderHTTPError("Gemini image API key is not configured")
        labels = reference_labels or [f"REFERENCE {index + 1}" for index in range(len(references))]
        if len(labels) != len(references):
            raise ProviderHTTPError("Gemini reference labels do not match reference count")

        interaction_input: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for label, reference in zip(labels, references):
            interaction_input.append({"type": "text", "text": label})
            interaction_input.append({
                "type": "image",
                "mime_type": _guess_mime(reference),
                "data": base64.b64encode(reference).decode("ascii"),
            })

        payload: dict[str, Any] = {
            "model": model,
            "input": interaction_input,
            "response_format": {
                "type": "image",
                "mime_type": "image/jpeg",
                "aspect_ratio": "4:5",
                "image_size": "2K",
            },
        }
        response = await asyncio.to_thread(
            _post_json,
            _interactions_url(self.api_base),
            {"x-goog-api-key": self.api_key},
            payload,
            self.timeout_s,
        )
        return _extract_interaction_image(response)


@dataclass(slots=True)
class SegmindFaceSwapRESTTransport:
    endpoint: str
    api_key: str
    timeout_s: int = 600
    face_restore: str = ""

    async def swap(self, *, source_face: bytes, target_scene: bytes) -> bytes:
        if not self.endpoint:
            raise ProviderHTTPError("Segmind FaceSwap URL is not configured")
        if not self.api_key:
            raise ProviderHTTPError("SEGMIND_API_KEY is not configured")
        source_jpeg = await asyncio.to_thread(_normalize_jpeg, source_face, max_side=1600)
        target_jpeg = await asyncio.to_thread(_normalize_jpeg, target_scene, max_side=2048)
        payload: dict[str, Any] = {
            "source_img": base64.b64encode(source_jpeg).decode("ascii"),
            "target_img": base64.b64encode(target_jpeg).decode("ascii"),
            "input_faces_index": "0",
            "source_faces_index": "0",
            "base64": False,
        }
        restore = (self.face_restore or "").strip()
        if restore and restore.lower() not in {"none", "off", "false", "0"}:
            payload["face_restore"] = restore
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
