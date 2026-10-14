"""Official Google Gemini API adapter for native Veo 3.1 extension.

The Gemini API accepts a previous Veo video as the ``video`` input to the same
long-running ``predictLongRunning`` method. Each extension returns one
cumulative video, so the bytes from that result are the only input to the next
extension. No independent scenes are generated or stitched together.
"""
from __future__ import annotations

import base64
import time

import httpx


class GoogleVeoError(RuntimeError):
    pass


class GoogleVeoSubmissionUncertain(GoogleVeoError):
    """The Google POST outcome is unknown; never resubmit automatically."""


class GoogleVeoPollUncertain(GoogleVeoError):
    """A submitted operation exists but its terminal result is not known."""


class GoogleVeoOperationFailed(GoogleVeoError):
    """Google returned a terminal, confirmed operation failure."""


class GoogleVeoQuotaExceeded(GoogleVeoError):
    """Google rejected a new request because the project quota is exhausted.

    A 429 response is an explicit rejection and does not contain an operation
    ID, so it is safe to retry only after the user explicitly asks to resume.
    """


class GoogleVeoVideo(bytes):
    """Downloaded Veo bytes retaining the provider video reference.

    The REST endpoint currently rejects ``video.inlineData`` for Veo 3.1
    Fast. The SDK contract instead passes the provider's previous ``Video``
    object. Keeping the URI attached to the bytes lets existing artifact and
    Telegram code continue treating results as MP4 bytes while the extension
    pipeline forwards the native provider reference.
    """

    def __new__(cls, payload: bytes, *, provider_uri: str | None = None,
                descriptor: dict | None = None):
        obj = bytes.__new__(cls, payload)
        obj.provider_uri = provider_uri
        obj.descriptor = descriptor
        return obj


def build_generate_payload(prompt: str, *, aspect_ratio: str = "16:9") -> dict:
    if not prompt.strip():
        raise ValueError("Veo prompt is required")
    if aspect_ratio not in ("9:16", "16:9"):
        raise ValueError("Veo aspect ratio must be 9:16 or 16:9")
    return {
        "instances": [{"prompt": prompt.strip()}],
        "parameters": {
            "resolution": "720p",
            "aspectRatio": aspect_ratio,
            "durationSeconds": 8,
        },
    }


def build_extend_payload(video_uri: str, prompt: str) -> dict:
    if not isinstance(video_uri, str) or not video_uri.strip():
        raise ValueError("Previous Google Veo video URI is required")
    if not prompt.strip():
        raise ValueError("Veo extension prompt is required")
    return {
        "instances": [{
            "prompt": prompt.strip(),
            "video": {"uri": video_uri.strip()},
        }],
        "parameters": {"resolution": "720p"},
    }


def extract_operation_name(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("name", "operationName"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        operation = payload.get("operation")
        if isinstance(operation, dict):
            return extract_operation_name(operation)
    raise ValueError("Google Veo response did not contain an operation name")


def _walk_video_nodes(payload: object):
    if isinstance(payload, dict):
        for key in ("video", "generatedVideo", "generatedVideos", "generatedSamples", "samples"):
            if key in payload:
                yield from _walk_video_nodes(payload[key])
        if any(key in payload for key in ("uri", "gcsUri", "videoBytes", "bytesBase64Encoded", "inlineData")):
            yield payload
        for key, value in payload.items():
            if key not in ("video", "generatedVideo", "generatedVideos", "generatedSamples", "samples"):
                if isinstance(value, (dict, list)):
                    yield from _walk_video_nodes(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_video_nodes(value)


def extract_video_descriptor(payload: object) -> dict:
    for node in _walk_video_nodes(payload):
        if isinstance(node, dict):
            return node
    raise GoogleVeoError("Google Veo operation completed without a video descriptor")


class GoogleVeoClient:
    def __init__(self, api_key: str, *, base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 model: str = "veo-3.1-fast-generate-preview", timeout_s: float = 120.0,
                 poll_interval_s: float = 10.0, max_wait_s: float = 1200.0):
        if not api_key:
            raise ValueError("GEMINI_VIDEO_API_KEY is missing")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.max_wait_s = max_wait_s

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    async def _submit(self, payload: dict) -> str:
        url = f"{self.base_url}/models/{self.model}:predictLongRunning"
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
            try:
                response = await client.post(url, headers=self._headers, json=payload)
            except httpx.RequestError as exc:
                raise GoogleVeoSubmissionUncertain(
                    "Google Veo submission outcome is unknown; do not retry"
                ) from exc
        if response.status_code >= 400:
            if response.status_code == 429:
                raise GoogleVeoQuotaExceeded(
                    f"Google Veo HTTP 429: {response.text[:500]}"
                )
            if response.status_code >= 500:
                raise GoogleVeoSubmissionUncertain(
                    f"Google Veo submission returned HTTP {response.status_code}; "
                    "the outcome is not safe to resubmit automatically"
                )
            raise GoogleVeoError(
                f"Google Veo HTTP {response.status_code}: {response.text[:500]}"
            )
        try:
            return extract_operation_name(response.json())
        except (ValueError, TypeError) as exc:
            raise GoogleVeoSubmissionUncertain(
                "Google Veo accepted response did not contain an operation ID"
            ) from exc

    async def submit_initial(self, prompt: str, *, reference_image: str | None = None) -> str:
        payload = build_generate_payload(prompt)
        if reference_image:
            from pathlib import Path
            path = Path(reference_image)
            if not path.is_file():
                raise FileNotFoundError("Google Veo presenter reference is missing")
            suffix = path.suffix.lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix)
            if not mime:
                raise ValueError("Google Veo reference must be JPEG, PNG or WebP")
            payload["instances"][0]["image"] = {
                "inlineData": {"mimeType": mime, "data": base64.b64encode(path.read_bytes()).decode("ascii")}
            }
        return await self._submit(payload)

    async def extend(self, video_uri: str, prompt: str) -> bytes:
        operation = await self._submit(build_extend_payload(video_uri, prompt))
        return await self.poll_bytes(operation)

    async def poll_bytes(self, operation_name: str) -> bytes:
        deadline = time.monotonic() + self.max_wait_s
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
            while time.monotonic() < deadline:
                try:
                    response = await client.get(
                        f"{self.base_url}/{operation_name.lstrip('/')}",
                        headers={"x-goog-api-key": self.api_key},
                    )
                except httpx.RequestError as exc:
                    raise GoogleVeoPollUncertain("Google Veo polling failed") from exc
                if response.status_code >= 400:
                    raise GoogleVeoPollUncertain(
                        f"Google Veo poll HTTP {response.status_code}: {response.text[:500]}"
                    )
                payload = response.json()
                if payload.get("done") is True:
                    if payload.get("error"):
                        raise GoogleVeoOperationFailed(f"Google Veo operation failed: {payload['error']}")
                    try:
                        descriptor = extract_video_descriptor(payload)
                        return await self._download_descriptor(client, descriptor)
                    except GoogleVeoOperationFailed:
                        raise
                    except Exception as exc:
                        # The operation has already been accepted. A malformed
                        # terminal payload or download failure is recoverable by
                        # polling the same operation, not by submitting again.
                        raise GoogleVeoPollUncertain(
                            "Google Veo completed but its video artifact could not be retrieved"
                        ) from exc
                await _async_sleep(self.poll_interval_s)
        raise GoogleVeoPollUncertain(
            "Google Veo operation polling timed out; reconcile the existing operation before retry"
        )

    async def _download_descriptor(self, client, descriptor: dict) -> bytes:
        inline = descriptor.get("videoBytes") or descriptor.get("bytesBase64Encoded")
        if isinstance(inline, str):
            return GoogleVeoVideo(base64.b64decode(inline), descriptor=descriptor)
        inline_data = descriptor.get("inlineData")
        if isinstance(inline_data, dict) and isinstance(inline_data.get("data"), str):
            return GoogleVeoVideo(base64.b64decode(inline_data["data"]), descriptor=descriptor)
        uri = descriptor.get("uri") or descriptor.get("gcsUri")
        if not isinstance(uri, str) or not uri.startswith("https://"):
            raise GoogleVeoError("Google Veo returned no downloadable HTTPS video URI")
        result = await client.get(uri, headers={"x-goog-api-key": self.api_key})
        result.raise_for_status()
        if not result.content:
            raise GoogleVeoError("Google Veo returned an empty video")
        return GoogleVeoVideo(result.content, provider_uri=uri, descriptor=descriptor)


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)
