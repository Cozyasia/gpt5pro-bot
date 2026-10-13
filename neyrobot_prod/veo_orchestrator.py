"""Provider-neutral orchestration for multi-scene Veo jobs.

The caller injects a generator returning MP4 bytes and a delivery callback.
No automatic retry after an ambiguous provider response: a task may be billed.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Awaitable, Callable

from .veo_multiscene import plan_video
from .veo_scene_prompt import scene_prompt
from .veo_assembler import assemble_vertical_video

GenerateScene = Callable[[str, int, int], Awaitable[bytes]]
Progress = Callable[[int, int], Awaitable[None]]


class SceneGenerationError(RuntimeError):
    def __init__(self, index: int, total: int):
        super().__init__(f"Scene {index}/{total} failed; no further paid requests submitted")
        self.index = index
        self.total = total


async def render_multiscene_video(
    *, duration_seconds: int, spoken_script: str, visual_brief: str,
    generate_scene: GenerateScene, output_path: str | Path,
    progress: Progress | None = None,
    presenter: str = "",
) -> Path:
    """Generate each scene once, validate MP4 and assemble one deliverable.

    Requires caller-side durable task registry, credit reservation and job lock
    before enabling for users. Output is written only after all scenes succeed.
    """
    scenes = plan_video(duration_seconds, spoken_script)
    destination = Path(output_path).resolve()
    with TemporaryDirectory(prefix="veo_multiscene_") as tmp:
        paths = []
        for scene in scenes:
            if progress is not None:
                await progress(scene.index, len(scenes))
            prompt = scene_prompt(scene, visual_brief, presenter=presenter)
            try:
                payload = await generate_scene(prompt, scene.index, len(scenes))
                if not isinstance(payload, bytes) or len(payload) < 1024:
                    raise ValueError("Provider returned empty or invalid video bytes")
                clip_path = Path(tmp) / f"scene_{scene.index:02d}.mp4"
                clip_path.write_bytes(payload)
                paths.append(clip_path)
            except Exception as exc:
                raise SceneGenerationError(scene.index, len(scenes)) from exc
        return assemble_vertical_video(paths, destination, duration_seconds)
