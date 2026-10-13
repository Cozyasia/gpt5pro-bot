"""CometAPI Veo single-shot multipart submission.

Never retry an ambiguous POST: provider may already have charged for it.
"""
from __future__ import annotations
import httpx


class UncertainVeoSubmission(RuntimeError):
    pass


async def submit_veo_task(base_url: str, api_key: str, model: str, prompt: str) -> str:
    if not api_key:
        raise ValueError("COMET_API_KEY missing")
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            response = await client.post(
                base_url.rstrip("/") + "/v1/videos",
                headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
                files=[("model", (None, model)), ("prompt", (None, prompt)),
                       ("size", (None, "9:16"))],
            )
        except httpx.RequestError as exc:
            raise UncertainVeoSubmission("Veo POST outcome unknown; do not resubmit") from exc
        if response.status_code >= 400:
            response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise UncertainVeoSubmission("Veo accepted response is not JSON") from exc
        if not isinstance(payload, dict):
            raise UncertainVeoSubmission("Veo response has no task object")
        for node in (payload, payload.get("data"), payload.get("result")):
            if isinstance(node, dict):
                for field in ("id", "task_id", "generation_id", "video_id", "taskId", "taskID", "request_id", "uuid"):
                    if node.get(field):
                        return str(node[field])
        raise UncertainVeoSubmission("Veo accepted response lacks task ID")
