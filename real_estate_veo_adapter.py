"""Compatibility renderer for callers that only request Google Veo.

The production paid path lives in ``property_video_execution``.  This adapter
keeps the older injected-renderer interface useful for offline/integration
callers while using the same multi-scene Veo transport and FFmpeg assembler.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from property_video_pipeline import assemble_property_video, plan_property_scenes, render_scene, scene_prompt
from real_estate_pipeline import fetch_telegram_photos


def make_google_veo_renderer(bot, root="/data/real_estate_jobs"):
    async def render(engine: str, photos: list[str], prompt: str, mode: str, duration: int):
        if engine != "veo":
            raise ValueError("This compatibility renderer only supports Google Veo")
        if not photos:
            raise ValueError("At least one reference photo is required")
        directory = Path(root) / uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        references = await fetch_telegram_photos(bot, photos[:10], str(directory / "references"))
        scenes = plan_property_scenes(len(references), duration, "veo", mode)
        paths = []
        for scene in scenes:
            content = await render_scene(
                "veo", references[scene.photo_index], scene_prompt(prompt, scene, len(scenes)), scene.seconds
            )
            target = directory / f"scene_{scene.index:02d}.mp4"
            target.write_bytes(content)
            paths.append(str(target))
        output = directory / "result.mp4"
        assemble_property_video(paths, str(output), duration)
        return str(output)
    return render
