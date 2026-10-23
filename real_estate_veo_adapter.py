"""Opt-in Veo real-estate renderer, using the repository's existing Google adapter.

Single reference image, single 8-second scene only. No billing bypass, no
automatic paid retries, and no assertion of multi-image support.
"""
from __future__ import annotations
import os
from pathlib import Path
from uuid import uuid4
from neyrobot_prod.veo_google_adapter import GoogleVeoClient
from real_estate_pipeline import fetch_telegram_photos


def make_google_veo_renderer(bot, root="/data/real_estate_jobs"):
    async def render(engine: str, photos: list[str], prompt: str, mode: str, duration: int):
        if engine != "veo":
            raise ValueError("This renderer only supports Google Veo")
        if duration != 8:
            raise ValueError("Veo single-shot requires 8 seconds; multi-scene is not yet enabled")
        if not photos:
            raise ValueError("At least one reference photo is required")
        key = os.getenv("GEMINI_VIDEO_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Google Veo API key is not configured")
        directory = Path(root) / uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        references = await fetch_telegram_photos(bot, photos[:1], str(directory))
        client = GoogleVeoClient(
            key, base_url=os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
            model=os.getenv("VEO_GOOGLE_MODEL", "veo-3.1-fast-generate-preview"),
        )
        # Persist operation name before polling. Never submit again automatically
        # if an accepted task cannot be polled or downloaded.
        operation = await client.submit_initial(prompt, reference_image=references[0], aspect_ratio="9:16")
        (directory / "operation.txt").write_text(operation, encoding="utf-8")
        video = await client.poll_bytes(operation)
        target = directory / "result.mp4"
        target.write_bytes(video)
        return str(target)
    return render
