"""Provider-neutral multi-scene pipeline for real-estate video reviews.

The wizard accepts up to ten ordered photographs, but every provider request is
kept to one reference image.  This is intentional: it preserves the existing
provider contracts and prevents the model from silently treating a collage as
the property reference.  The final MP4 is assembled locally with FFmpeg.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from real_estate_pipeline import concatenate_mp4
from video_studio import seedance_generate
from neyrobot_prod.veo_google_adapter import GoogleVeoClient


class PropertyVideoError(RuntimeError):
    """A safe, user-visible property-video error."""


@dataclass(frozen=True)
class PropertyScene:
    index: int
    photo_index: int
    seconds: int
    role: str


def _scene_count(photo_count: int, duration: int, engine: str) -> int:
    if engine == "veo":
        provider_scene_seconds = 8
    elif engine == "kling":
        provider_scene_seconds = 10
    else:
        provider_scene_seconds = 10
    return min(photo_count, max(1, math.ceil(duration / provider_scene_seconds)))


def plan_property_scenes(photo_count: int, duration: int, engine: str, mode: str) -> list[PropertyScene]:
    """Plan ordered reference shots without inventing a floor plan.

    Veo emits native 8-second clips; the final assembler trims the cumulative
    result to the requested duration. Kling and Seedance receive 4–10 second
    scene durations so the requested duration is represented more closely.
    """
    engine = str(engine or "").strip().lower()
    mode = str(mode or "").strip().lower()
    if engine not in {"kling", "veo", "seedance"}:
        raise ValueError("Unsupported property-video engine")
    if mode not in {"exterior", "interior", "full"}:
        raise ValueError("Unsupported property-video mode")
    if not 1 <= int(photo_count) <= 10:
        raise ValueError("Property video requires 1 to 10 photos")
    duration = int(duration)
    if duration not in {8, 10, 20, 30}:
        raise ValueError("Unsupported property-video duration")

    count = _scene_count(int(photo_count), duration, engine)
    if engine == "veo":
        seconds = [8] * count
    else:
        base, remainder = divmod(duration, count)
        seconds = [base + (1 if i < remainder else 0) for i in range(count)]
        seconds = [max(4, min(10, value)) for value in seconds]

    scenes: list[PropertyScene] = []
    for i, scene_seconds in enumerate(seconds):
        if mode == "exterior":
            role = "exterior establishing view" if i == 0 else "exterior architectural detail"
        elif mode == "interior":
            role = "interior room view"
        else:
            role = "exterior establishing view" if i == 0 else "interior/property detail view"
        scenes.append(PropertyScene(i, i % int(photo_count), int(scene_seconds), role))
    return scenes


def scene_prompt(base_prompt: str, scene: PropertyScene, total: int) -> str:
    return (
        f"{base_prompt.strip()}\n"
        f"This is shot {scene.index + 1} of {total}, role: {scene.role}. "
        "Use only the supplied reference photograph for this shot. Preserve the "
        "exact architecture, room geometry, furniture, windows, doors, pool and "
        "landscaping that are visible. Do not invent rooms, amenities, connections, "
        "objects or a floor plan. Smooth realistic camera motion only; no text, "
        "logos, watermarks, morphing or warped geometry."
    ).strip()


def _read(path: str) -> bytes:
    data = Path(path).read_bytes()
    if not data:
        raise PropertyVideoError("Reference photo is empty")
    return data


async def render_scene(
    engine: str,
    photo_path: str,
    prompt: str,
    seconds: int,
    *,
    on_task_id: Callable[[str], None] | None = None,
) -> bytes:
    """Render one scene through the project's existing provider transports."""
    engine = engine.strip().lower()
    if engine == "veo":
        key = os.getenv("GEMINI_VIDEO_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise PropertyVideoError("Google Veo API key is not configured")
        client = GoogleVeoClient(
            key,
            base_url=os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
            model=os.getenv("VEO_GOOGLE_MODEL", "veo-3.1-fast-generate-preview"),
            poll_interval_s=float(os.getenv("PROPERTY_VIDEO_VEO_POLL_INTERVAL_S", "10")),
            max_wait_s=float(os.getenv("PROPERTY_VIDEO_PROVIDER_MAX_WAIT_S", "1800")),
        )
        operation = await client.submit_initial(prompt, reference_image=photo_path, aspect_ratio="9:16")
        if on_task_id:
            on_task_id(operation)
        return bytes(await client.poll_bytes(operation))

    image = _read(photo_path)
    if engine == "kling":
        key = os.getenv("KLING_API_KEY") or os.getenv("COMET_API_KEY")
        if not key:
            raise PropertyVideoError("Kling/Comet API key is not configured")
        # Reuse the production Kling image-to-video transport already used by
        # photo clips, including its status polling and task-id callback.
        import main as production_main
        renderer = getattr(production_main, "_run_kling_photo_clip_result", None)
        if not callable(renderer):
            raise PropertyVideoError("Existing Kling image-to-video transport is unavailable")
        result = await renderer(
            image,
            prompt,
            int(seconds),
            "9:16",
            image_url="",
            on_task_id=on_task_id,
        )
        if not result:
            raise PropertyVideoError("Kling returned an empty video")
        return bytes(result)

    key = os.getenv("COMET_API_KEY") or os.getenv("COMETAPI_KEY")
    if not key:
        raise PropertyVideoError("Seedance/Comet API key is not configured")
    task_id = None
    result = await seedance_generate(
        api_key=key,
        base_url=os.getenv("COMET_BASE_URL", "https://api.cometapi.com"),
        prompt=prompt,
        seconds=int(seconds),
        aspect="9:16",
        model=os.getenv("SEEDANCE_MODEL", "seedance-2-5-260628"),
        model_fallbacks=[x.strip() for x in os.getenv("SEEDANCE_MODEL_FALLBACKS", "seedance-2-5,seedance-2-5-260628").split(",") if x.strip()],
        reference_bytes=image,
        reference_name=Path(photo_path).name,
        create_path=os.getenv("SEEDANCE_CREATE_PATH", "/v1/videos"),
        max_wait_s=float(os.getenv("PROPERTY_VIDEO_PROVIDER_MAX_WAIT_S", "1800")),
        on_task_id=on_task_id,
    )
    return bytes(result)


def assemble_property_video(scene_paths: list[str], output_path: str, duration: int) -> str:
    """Normalize, concatenate and trim scenes to one Telegram-safe MP4."""
    if not scene_paths:
        raise PropertyVideoError("No generated scenes to assemble")
    assembled = concatenate_mp4(scene_paths, output_path)
    target = Path(output_path)
    if int(duration) <= 0:
        return assembled
    trimmed = target.with_name(target.stem + ".trimmed.mp4")
    import subprocess
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-i", str(target), "-t", str(int(duration)),
            "-c:v", "libx264", "-preset", os.getenv("PROPERTY_VIDEO_FFMPEG_PRESET", "veryfast"),
            "-crf", os.getenv("PROPERTY_VIDEO_FFMPEG_CRF", "23"), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(trimmed),
        ],
        check=True,
        capture_output=True,
        timeout=int(os.getenv("PROPERTY_VIDEO_FFMPEG_TIMEOUT_S", "600")),
    )
    trimmed.replace(target)
    return str(target)


def scene_manifest(scenes: list[PropertyScene]) -> list[dict]:
    return [asdict(scene) for scene in scenes]
