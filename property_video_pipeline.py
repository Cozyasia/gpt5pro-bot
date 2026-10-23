"""Provider-neutral multi-scene pipeline for real-estate video reviews.

Each provider request uses one source photograph because that is the existing
provider contract. The planner nevertheless creates a montage slot for every
uploaded photograph (and repeats a photograph only when the requested runtime
is longer than the provider clip limit). FFmpeg trims each generated clip to
its assigned slot, so a long provider clip cannot hide later references.
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
    output_seconds: float
    next_photo_index: int | None = None


def _provider_clip_limit(engine: str) -> int:
    return 8 if engine == "veo" else 10


def _provider_seconds(engine: str, output_seconds: float) -> int:
    """Return a supported provider duration for one output montage slot."""
    if engine == "veo":
        return 8
    if engine == "kling":
        # The production Kling transport normalizes <7s to 5s and >=7s to 10s.
        return 10 if output_seconds > 5 else 5
    return max(4, min(30, int(math.ceil(output_seconds))))


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

    # Kling and Gemini Omni accept first/last reference frames, so consecutive
    # photos can form a real transition and ten photos become five usable
    # scenes. The existing Comet Seedance contract accepts one multipart
    # reference only; keep every uploaded photo as a scene source there instead
    # of silently dropping the odd-numbered references.
    transition_capable = engine in {"kling", "veo"}
    minimum_scene_count = math.ceil(int(photo_count) / 2) if transition_capable else int(photo_count)
    count = max(minimum_scene_count, math.ceil(duration / _provider_clip_limit(engine)))
    slot_seconds = duration / count

    scenes: list[PropertyScene] = []
    for i in range(count):
        if mode == "exterior":
            role = "visible exterior property view"
        elif mode == "interior":
            role = "visible interior room view"
        else:
            # Upload order is the only reliable sequence signal. Do not label a
            # frame interior/exterior without analysing its pixels.
            role = "property establishing view" if i == 0 else "property view in upload order"
        first_photo = min(i * 2, int(photo_count) - 1) if transition_capable else min(i, int(photo_count) - 1)
        next_photo = (
            i * 2 + 1 if i * 2 + 1 < int(photo_count) else None
        ) if transition_capable else None
        scenes.append(PropertyScene(
            i, first_photo, _provider_seconds(engine, slot_seconds), role,
            round(slot_seconds, 3),
            next_photo,
        ))
    return scenes


def scene_prompt(base_prompt: str, scene: PropertyScene, total: int) -> str:
    if "interior" in scene.role:
        visible_constraints = (
            "Preserve only the visible room geometry, walls, ceiling, floor, windows, doors, "
            "materials, furniture and lighting. Do not add exterior views, rooms or amenities."
        )
    elif "exterior" in scene.role:
        visible_constraints = (
            "Preserve only the visible facade, roof, windows, doors, pool, landscaping, "
            "terrain and outdoor furniture. Do not add rooms or unseen structures."
        )
    else:
        visible_constraints = (
            "Preserve only the visible architecture, room geometry, materials, furniture, "
            "landscaping and lighting; do not infer whether unseen areas exist."
        )
    transition = ""
    if scene.next_photo_index is not None:
        transition = (
            f" The next reference photo is photo {scene.next_photo_index + 1}; "
            "move the camera through a continuous walkthrough and finish on that "
            "next photographed view, without inventing an intermediate room."
        )
    reference_instruction = (
        "Use only this supplied reference photograph as the source for this shot."
        if scene.next_photo_index is None else
        "Use only this supplied reference photograph as the source and the named next "
        "reference photograph as the terminal frame for this shot."
    )
    return (
        f"{base_prompt.strip()}\n"
        f"This is shot {scene.index + 1} of {total}, source photo {scene.photo_index + 1}, "
        f"role: {scene.role}. {reference_instruction} "
        f"{visible_constraints}{transition} Do not invent rooms, amenities, connections, objects or a "
        "floor plan. Smooth realistic camera motion only; no text, logos, watermarks, "
        "morphing or warped geometry. Do not blend in content from an unrelated shot."
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
    output_path: str = "",
    last_photo_path: str = "",
) -> bytes | str:
    """Render one scene through the project's existing provider transports."""
    engine = engine.strip().lower()
    if engine == "veo":
        key = os.getenv("GEMINI_VIDEO_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise PropertyVideoError("Google Veo API key is not configured")
        model = os.getenv("VEO_GOOGLE_MODEL", "gemini-omni-1.1-flash")
        if model in {"veo-3.1-fast-generate-preview", "veo-3.1-generate-preview", "veo-3.1-lite-generate-preview"}:
            model = "gemini-omni-1.1-flash"
        client = GoogleVeoClient(
            key,
            base_url=os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
            model=model,
            poll_interval_s=float(os.getenv("PROPERTY_VIDEO_VEO_POLL_INTERVAL_S", "10")),
            max_wait_s=float(os.getenv("PROPERTY_VIDEO_PROVIDER_MAX_WAIT_S", "1800")),
        )
        operation = await client.submit_initial(
            prompt,
            reference_image=photo_path,
            reference_image_last=last_photo_path or None,
            aspect_ratio="9:16",
        )
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
        # Kling/Comet validates the image asynchronously and rejects data URLs
        # with UrlIllegal. Publish the downloaded Telegram photo through the
        # existing short-lived HTTPS artifact endpoint used by other Kling
        # flows, then pass that URL to the existing production transport.
        input_url_factory = getattr(production_main, "_provider_input_url_from_file", None)
        if not callable(input_url_factory):
            raise PropertyVideoError("Provider input URL transport is unavailable")
        image_url = input_url_factory(photo_path, Path(photo_path).name)
        image_tail_url = ""
        if last_photo_path:
            image_tail_url = input_url_factory(last_photo_path, Path(last_photo_path).name)
        result = await renderer(
            image,
            prompt,
            int(seconds),
            "9:16",
            image_url=image_url,
            on_task_id=on_task_id,
            output_path=output_path,
            prompt_mode="property",
            image_tail_url=image_tail_url,
        )
        if not result:
            raise PropertyVideoError("Kling returned an empty video")
        if output_path and isinstance(result, str):
            return result
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


async def render_scene_to_file(
    engine: str,
    photo_path: str,
    prompt: str,
    seconds: int,
    output_path: str,
    *,
    on_task_id: Callable[[str], None] | None = None,
    last_photo_path: str = "",
) -> str:
    """Render one scene and persist it before the next provider result is fetched.

    Kling can stream its result directly to ``output_path``. The other existing
    transports still return bytes, so this wrapper writes and releases that
    payload immediately instead of keeping completed scenes alive across the
    multi-scene loop.
    """
    target = Path(output_path)
    result = await render_scene(
        engine, photo_path, prompt, seconds,
        on_task_id=on_task_id,
        output_path=str(target) if engine.strip().lower() == "kling" else "",
        last_photo_path=last_photo_path,
    )
    if isinstance(result, str):
        if Path(result).resolve() != target.resolve() and Path(result).is_file():
            Path(result).replace(target)
    else:
        target.write_bytes(result)
        del result
    if not target.is_file() or target.stat().st_size < 512:
        raise PropertyVideoError("Provider returned an empty video file")
    return str(target)


def assemble_property_video(scene_paths: list[str], output_path: str, duration: int, scene_durations: list[float] | None = None) -> str:
    """Normalize, concatenate and trim scenes to one Telegram-safe MP4."""
    if not scene_paths:
        raise PropertyVideoError("No generated scenes to assemble")
    assembled = concatenate_mp4(
        scene_paths,
        output_path,
        durations=scene_durations,
        retime_to_fit=scene_durations is not None,
    )
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
