"""CometAPI Veo 3.1 native-audio extension. Paid calls are never auto-retried."""
from __future__ import annotations
import httpx

class UncertainExtension(RuntimeError):
    pass

def build_extension_payload(previous_video_uri: str, continuation: str, model: str = "veo-3.1") -> dict:
    if not previous_video_uri.startswith(("https://", "http://")):
        raise ValueError("Veo extension requires provider-hosted HTTP(S) URI")
    if not continuation.strip():
        raise ValueError("Continuation prompt required")
    return {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": continuation.strip()}],
        "extra_body": {"google": {
            "video": {"uri": previous_video_uri},
            "config": {"numberOfVideos": 1, "resolution": "720p",
                       "durationSeconds": 7, "fps": 24, "generateAudio": True},
        }},
    }

def find_video_uri(payload: object) -> str | None:
    """Accept only a provider video URI, never invent a public URL."""
    if isinstance(payload, dict):
        for k in ("video_uri", "video_url", "output_url", "url", "uri"):
            v = payload.get(k)
            if isinstance(v, str) and v.startswith(("https://", "http://")) and (k in ("video_uri", "video_url", "output_url") or ".mp4" in v or "/video" in v):
                return v
        for k in ("generated_videos", "videos", "video", "data", "result", "output", "choices", "message", "content"):
            if k in payload:
                uri = find_video_uri(payload[k])
                if uri:
                    return uri
    if isinstance(payload, list):
        for item in payload:
            uri = find_video_uri(item)
            if uri:
                return uri
    return None

async def extend_veo(base_url: str, api_key: str, previous_video_uri: str,
                     continuation: str, *, model: str = "veo-3.1") -> tuple[str | None, dict]:
    if not api_key:
        raise ValueError("COMET_API_KEY is missing")
    body = build_extension_payload(previous_video_uri, continuation, model)
    async with httpx.AsyncClient(timeout=150, follow_redirects=True) as client:
        try:
            response = await client.post(base_url.rstrip("/") + "/v1/chat/completions",
                headers={"Authorization": "Bearer " + api_key,
                         "Content-Type": "application/json"},
                json=body)
        except httpx.RequestError as exc:
            raise UncertainExtension("Comet Veo Extend submission outcome unknown; do not retry") from exc
    if response.status_code >= 400:
        raise RuntimeError("Comet Veo Extend HTTP " + str(response.status_code) + ": " + response.text[:450])
    try:
        payload = response.json()
    except ValueError as exc:
        raise UncertainExtension("Comet Veo Extend returned non-JSON response") from exc
    if not isinstance(payload, dict):
        raise UncertainExtension("Comet Veo Extend returned unexpected response")
    return find_video_uri(payload), payload
