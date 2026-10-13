"""HeyGen v3 API adapter for Russian talking-presenter videos.

Direct HeyGen API: not routed through CometAPI unless Comet documents a
compatible HeyGen endpoint. Never retry an ambiguous paid submission.
"""
from __future__ import annotations
import asyncio
import httpx

BASE_URL = "https://api.heygen.com"

class UncertainHeyGenSubmission(RuntimeError):
    pass

async def create_presenter_video(api_key: str, avatar_id: str, voice_id: str,
                                 script: str, *, title: str = "Neyro-Bot Studio") -> str:
    if not all((api_key, avatar_id, voice_id, script.strip())):
        raise ValueError("HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_VOICE_ID and script required")
    payload = {"avatar_id": avatar_id, "voice_id": voice_id,
               "script": script.strip(), "title": title,
               "resolution": "1080p", "aspect_ratio": "9:16"}
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(BASE_URL + "/v3/videos",
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                json=payload)
        except httpx.RequestError as exc:
            raise UncertainHeyGenSubmission("HeyGen POST status unknown: do not resubmit") from exc
        response.raise_for_status()
        data = response.json()
        for node in (data, data.get("data"), data.get("result")):
            if isinstance(node, dict):
                for field in ("video_id", "id"):
                    if node.get(field):
                        return str(node[field])
        raise UncertainHeyGenSubmission("HeyGen response lacks video ID; do not resubmit")

async def poll_presenter_video(api_key: str, video_id: str, *, max_wait_seconds: int = 1200) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(max_wait_seconds // 10):
            response = await client.get(BASE_URL + "/v3/videos/" + video_id,
                headers={"X-Api-Key": api_key})
            response.raise_for_status()
            body = response.json()
            data = body.get("data", body) if isinstance(body, dict) else {}
            if not isinstance(data, dict):
                raise RuntimeError("Unexpected HeyGen status response")
            status = str(data.get("status") or data.get("state") or "").lower()
            if status in ("completed", "success", "succeeded"):
                url = data.get("video_url") or data.get("url")
                if not url and isinstance(data.get("video"), dict):
                    url = data["video"].get("url")
                if not url:
                    raise RuntimeError("HeyGen completed without a video URL")
                return str(url)
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError("HeyGen video failed: " + str(data.get("error") or status)[:300])
            await asyncio.sleep(10)
    raise TimeoutError("HeyGen processing continues; retain video ID for polling")
