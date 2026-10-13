"""CometAPI Veo single-shot multipart submission.

Never retry an ambiguous POST: provider may already have charged for it.
"""
from __future__ import annotations
import httpx
from pathlib import Path


class UncertainVeoSubmission(RuntimeError):
    pass


async def submit_veo_task(base_url: str, api_key: str, model: str, prompt: str, *, reference_image: str | None = None) -> str:
    if not api_key:
        raise ValueError("COMET_API_KEY missing")
    reference = Path(reference_image).resolve() if reference_image else None
    if reference is not None:
        if not reference.is_file() or reference.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ValueError("Veo reference must be an existing JPEG, PNG or WebP file")
        if reference.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Veo reference exceeds 10 MiB")
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            if reference is not None:
                image_bytes = reference.read_bytes()
                content_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[reference.suffix.lower()]
                parts = [("model", (None, model)), ("prompt", (None, prompt)),
                         ("size", (None, "9:16")),
                         ("input_reference", (reference.name, image_bytes, content_type))]
            else:
                parts = [("model", (None, model)), ("prompt", (None, prompt)),
                         ("size", (None, "9:16"))]
            response = await client.post(
                base_url.rstrip("/") + "/v1/videos",
                headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
                files=parts,
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
