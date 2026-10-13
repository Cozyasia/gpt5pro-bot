"""Resume-aware Veo pipeline connecting journal, artifacts and assembly.

Provider-specific submit/poll are injected. The caller MUST hold a cross-process
job lock and persist the job on a mounted volume (Render: /data).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from .veo_multiscene import plan_video
from .veo_scene_prompt import scene_prompt
from .veo_scene_runner import run_journaled_scene, ReconciliationRequired
from .veo_scene_artifacts import save_scene, list_complete_scenes
from .veo_task_journal import read_job
from .veo_assembler import assemble_vertical_video


async def resume_veo_job(
    *, job_directory: str | Path, duration_seconds: int,
    spoken_script: str, visual_brief: str,
    submit: Callable[[str, int], Awaitable[str]],
    poll: Callable[[str], Awaitable[bytes]],
    presenter: str = "",
    reference_image: str | Path | None = None,
) -> Path:
    """Create or resume scenes and return assembled MP4 path.

    Completed scenes are loaded, accepted scenes are polled, uncertain scenes
    halt for manual reconciliation. No automatic resubmission after acceptance.
    """
    directory = Path(job_directory)
    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / "journal.json"
    scenes = plan_video(duration_seconds, spoken_script)
    if reference_image is not None:
        reference_path = Path(reference_image).resolve()
        if not reference_path.is_file():
            raise FileNotFoundError("Veo presenter reference is missing")
    for scene in scenes:
        prior = read_job(journal)["scenes"].get(str(scene.index), {})
        if prior.get("state") == "completed":
            # Avoid loading paid MP4 bytes into RAM on 512 MiB Render.
            completed = list_complete_scenes(directory, scene.index)
            if len(completed) < scene.index:
                raise FileNotFoundError("Completed Veo scene artifact missing; do not resubmit")
            continue
        prompt = scene_prompt(scene, visual_brief, presenter=presenter)
        if reference_image is not None:
            prompt += "\nUse the attached input_reference image as the fixed presenter identity across every scene."
        async def submit_this(prompt=prompt, index=scene.index):
            return await submit(prompt, index)
        async def save_this(index, payload):
            await asyncio.to_thread(save_scene, directory, index, payload)
        await run_journaled_scene(journal, scene.index, submit_this, poll, save_this)
    clips = list_complete_scenes(directory, len(scenes))
    output = directory / "final.mp4"
    return await asyncio.to_thread(assemble_vertical_video, clips, output, duration_seconds)
