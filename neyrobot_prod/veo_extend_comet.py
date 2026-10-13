"""CometAPI Veo extension boundary.

CometAPI's current public API reference documents Veo generation through
``POST /v1/videos``. It does not publish a native Veo Extend endpoint. A
previous preview article showed an OpenAI-compatible chat example, but that
route is not a production contract and the live request failed with a
confirmed ``model_not_found``/``no available channel`` response.

Keep this module as an explicit guard so callers cannot accidentally turn the
undocumented preview example into a paid production dependency. Native
extension is implemented by ``veo_google_adapter.py`` instead.
"""
from __future__ import annotations


class CometExtensionUnavailable(RuntimeError):
    """Comet refused/does not expose native Veo Extend; no request was sent."""


class UncertainExtension(RuntimeError):
    """The outcome of a paid extension request cannot be determined."""


def build_extension_payload(*args, **kwargs) -> dict:
    raise CometExtensionUnavailable(
        "CometAPI public Veo Extend is unavailable; use the official Google "
        "native Veo provider"
    )


def find_video_uri(payload: object) -> str | None:
    """Extract only a provider-reported HTTP(S) video URL from a response."""
    if isinstance(payload, dict):
        for key in ("video_uri", "video_url", "output_url", "url", "uri"):
            value = payload.get(key)
            if (
                isinstance(value, str)
                and value.startswith(("https://", "http://"))
                and (
                    key in ("video_uri", "video_url", "output_url")
                    or ".mp4" in value
                    or "/video" in value
                )
            ):
                return value
        for key in (
            "generated_videos", "generatedVideos", "videos", "video", "data",
            "result", "output", "choices", "message", "content",
        ):
            if key in payload:
                uri = find_video_uri(payload[key])
                if uri:
                    return uri
    elif isinstance(payload, list):
        for item in payload:
            uri = find_video_uri(item)
            if uri:
                return uri
    return None


async def extend_veo(*args, **kwargs) -> tuple[str | None, dict]:
    """Reject the unsupported Comet route before creating any paid request."""
    raise CometExtensionUnavailable(
        "CometAPI does not expose a verified native Veo Extend route; "
        "no extension request was sent"
    )
