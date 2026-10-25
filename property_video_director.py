"""Vision-assisted reference analysis for the property-video director.

The analysis is deliberately advisory. Provider submissions remain bounded and
deterministic when the vision model is unavailable: upload order is preserved
and every unknown connection is treated as a cinematic cut, never as evidence
for an invented corridor.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Awaitable, Callable


log = logging.getLogger(__name__)

ALLOWED_SPACES = {
    "exterior", "entrance", "living_room", "dining_room", "kitchen",
    "bedroom", "bathroom", "terrace_pool", "corridor", "other", "unknown",
}


def parse_photo_analysis(value: str | dict | None) -> dict:
    """Return a small trusted label record from model output."""
    if isinstance(value, dict):
        raw = value
    else:
        text = str(value or "").strip()
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {"space": "unknown", "summary": ""}
        try:
            raw = json.loads(match.group(0))
        except (TypeError, ValueError):
            return {"space": "unknown", "summary": ""}
    space = str(raw.get("space") or "unknown").strip().lower().replace(" ", "_")
    aliases = {
        "pool": "terrace_pool", "terrace": "terrace_pool", "patio": "terrace_pool",
        "living": "living_room", "lounge": "living_room", "dining": "dining_room",
        "bed": "bedroom", "bath": "bathroom", "hallway": "corridor",
    }
    space = aliases.get(space, space)
    if space not in ALLOWED_SPACES:
        space = "unknown"
    summary = " ".join(str(raw.get("summary") or "").split())[:180]
    return {"space": space, "summary": summary}


def _analysis_image(path: str) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((768, 768))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii"), "image/jpeg"


async def _analyse_one_reference(path: str, index: int) -> dict:
    if os.getenv("PROPERTY_VIDEO_DIRECTOR_ANALYSIS_ENABLED", "1").strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return {"space": "unknown", "summary": ""}
    try:
        import main as production_main
        analyser = getattr(production_main, "ask_openai_vision", None)
        if not callable(analyser):
            return {"space": "unknown", "summary": ""}
        image_b64, mime = await asyncio.to_thread(_analysis_image, path)
        prompt = (
            "Classify this property reference for a real-estate video director. "
            "Return JSON only with keys space and summary. space must be exactly one of: "
            "exterior, entrance, living_room, dining_room, kitchen, bedroom, bathroom, "
            "terrace_pool, corridor, other. summary is a factual description under 20 words. "
            "Do not infer unseen rooms or connections. "
            f"Reference number: {index + 1}."
        )

        # The production vision helper currently wraps a synchronous SDK call
        # in an async function. Run that coroutine in a worker thread so up to
        # three photo analyses do not freeze Telegram's event loop.
        def invoke():
            return asyncio.run(analyser(prompt, image_b64, mime))

        response = await asyncio.to_thread(invoke)
        return parse_photo_analysis(response)
    except Exception:
        log.warning("PROPERTY_VIDEO_REFERENCE_ANALYSIS_FAILED index=%s path=%s", index, Path(path).name,
                    exc_info=True)
        return {"space": "unknown", "summary": ""}


async def analyse_reference_photos(
    photo_paths: list[str],
    *,
    analyser: Callable[[str, int], Awaitable[dict]] | None = None,
    concurrency: int = 3,
) -> list[dict]:
    """Analyse every uploaded reference while bounding model concurrency."""
    worker = analyser or _analyse_one_reference
    semaphore = asyncio.Semaphore(max(1, min(int(concurrency), 6)))

    async def run(index: int, path: str) -> dict:
        async with semaphore:
            try:
                return parse_photo_analysis(await worker(path, index))
            except Exception:
                log.warning("PROPERTY_VIDEO_REFERENCE_ANALYSIS_FAILED index=%s", index, exc_info=True)
                return {"space": "unknown", "summary": ""}

    return list(await asyncio.gather(*(run(index, path) for index, path in enumerate(photo_paths))))

