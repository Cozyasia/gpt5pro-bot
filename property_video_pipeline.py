"""Provider-neutral multi-scene pipeline for directed property walkthroughs.

Kling and Gemini Omni use an overlapping chain of selected route frames as
exact first/last references. Seedance keeps one selected reference per scene.
The assembler retimes complete clips into their montage slots so terminal
reference frames are preserved.
"""
from __future__ import annotations

import math
import os
import logging
import json
import subprocess
import io
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from real_estate_pipeline import concatenate_mp4
from video_studio import seedance_generate
from neyrobot_prod.veo_google_adapter import GoogleVeoClient


log = logging.getLogger(__name__)


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
    transition_kind: str = "continuous"
    source_label: str = "unknown"
    target_label: str = "unknown"


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


def _scene_budget(duration: int) -> int:
    return {8: 1, 10: 2, 20: 4, 30: 6, 45: 9, 60: 12}[int(duration)]


def _evenly_spaced_indices(photo_count: int, sample_count: int) -> list[int]:
    sample_count = max(1, min(int(sample_count), int(photo_count)))
    if sample_count == 1:
        return [0]
    last = int(photo_count) - 1
    return [round(i * last / (sample_count - 1)) for i in range(sample_count)]


def _director_indices(photo_count: int, sample_count: int, labels: list[str] | None) -> list[int]:
    """Prefer room boundaries, then fill remaining route slots evenly."""
    if not labels or len(labels) < int(photo_count):
        return _evenly_spaced_indices(photo_count, sample_count)
    boundaries = [0]
    for index in range(1, int(photo_count)):
        before = str(labels[index - 1] or "unknown")
        current = str(labels[index] or "unknown")
        if current != before:
            boundaries.append(index)
    if boundaries[-1] != int(photo_count) - 1:
        boundaries.append(int(photo_count) - 1)
    if len(boundaries) >= sample_count:
        positions = _evenly_spaced_indices(len(boundaries), sample_count)
        return [boundaries[index] for index in positions]
    chosen = set(boundaries)
    for index in _evenly_spaced_indices(photo_count, sample_count):
        chosen.add(index)
    if len(chosen) < sample_count:
        chosen.update(range(int(photo_count)))
    ordered = sorted(chosen)
    if len(ordered) > sample_count:
        positions = _evenly_spaced_indices(len(ordered), sample_count)
        ordered = [ordered[index] for index in positions]
    return ordered


def _transition_kind(source_label: str, target_label: str) -> str:
    source = str(source_label or "unknown")
    target = str(target_label or "unknown")
    if source == target and source not in {"unknown", "other"}:
        return "continuous"
    connected_groups = (
        {"exterior", "entrance", "terrace_pool"},
        {"living_room", "dining_room", "kitchen"},
    )
    if any(source in group and target in group for group in connected_groups):
        return "continuous"
    return "cinematic_cut"


def plan_property_scenes(
    photo_count: int,
    duration: int,
    engine: str,
    mode: str,
    *,
    selected_indices: list[int] | None = None,
    labels: list[str] | None = None,
) -> list[PropertyScene]:
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
    if not 1 <= int(photo_count) <= 30:
        raise ValueError("Property video requires 1 to 30 photos")
    duration = int(duration)
    if duration not in {8, 10, 20, 30, 45, 60}:
        raise ValueError("Unsupported property-video duration")

    # Kling and Gemini Omni accept first/last reference frames, so selected
    # photos form an overlapping route. The current Comet Seedance contract
    # accepts one reference per scene, so it receives selected route keyframes.
    transition_capable = engine in {"kling", "veo"}
    budget = _scene_budget(duration)
    if selected_indices is None:
        frame_count = min(int(photo_count), budget + 1 if transition_capable else budget)
        selected = _director_indices(int(photo_count), frame_count, labels)
    else:
        selected = [int(value) for value in selected_indices]
        if not selected or selected != sorted(set(selected)) or selected[0] < 0 or selected[-1] >= int(photo_count):
            raise ValueError("Selected property references must be ordered unique valid indices")
    count = max(1, len(selected) - 1) if transition_capable and len(selected) > 1 else len(selected)
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
        first_photo = selected[i]
        next_photo = selected[i + 1] if transition_capable and i + 1 < len(selected) else None
        source_label = labels[first_photo] if labels and first_photo < len(labels) else "unknown"
        target_label = labels[next_photo] if labels and next_photo is not None and next_photo < len(labels) else "unknown"
        scenes.append(PropertyScene(
            i, first_photo, _provider_seconds(engine, slot_seconds), role,
            round(slot_seconds, 3),
            next_photo,
            _transition_kind(source_label, target_label) if next_photo is not None else "single_reference",
            source_label,
            target_label,
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
        if scene.transition_kind == "continuous":
            connection = (
                "The references support a connected or same-zone move. Travel naturally through the visible "
                "three-dimensional space and reveal a new angle of the same architecture."
            )
        else:
            connection = (
                "The physical connection is not proven. Use a natural cinematic cut hidden by a real wall, "
                "doorframe, curtain or pillar filling the frame; do not invent a corridor or teleport through a wall."
            )
        transition = (
            f" The next reference photo is photo {scene.next_photo_index + 1} and is the LAST_FRAME. "
            "Create a first-person continuous walkthrough. The camera position physically travels while the operator "
            "walks through the actual three-dimensional environment depicted in the "
            "references. Camera height is approximately 1.6 metres with a realistic 20-24mm full-frame "
            "architectural lens. Generate spatial translation, foreground parallax against the background, changing perspective, "
            "natural acceleration, deceleration and subtle stabilized handheld micro-movement. "
            "Do not animate a flat photograph. " + connection + " "
            "Land faithfully on the exact LAST_FRAME. If authentic spatial movement would require invented geometry, "
            "prefer a shorter accurate shot rather than a fake walkthrough. No digital zoom, static pan, Ken Burns "
            "effect, dissolve, teleportation or geometry morph."
        )
    reference_instruction = (
        "Use only this supplied reference photograph as the source for this shot."
        if scene.next_photo_index is None else
        "Use only this supplied reference photograph as the source and the named next "
        "reference photograph as the terminal frame for this shot."
    )
    return (
        f"DIRECTOR SHOT {scene.index + 1} OF {total}. Source photo {scene.photo_index + 1}. "
        f"role: {scene.role}. {reference_instruction} "
        f"{visible_constraints}{transition} Do not invent rooms, amenities, connections, objects or a "
        "floor plan. Smooth realistic camera motion only; no text, logos, watermarks, "
        "morphing or warped geometry. Do not blend in content from an unrelated shot.\n"
        f"PROJECT DIRECTION: {base_prompt.strip()}"
    ).strip()


def resolve_reference_aspect(photo_paths: list[str], requested: str = "auto") -> str:
    requested = str(requested or "auto").strip().lower()
    if requested in {"9:16", "16:9"}:
        return requested
    if requested != "auto":
        raise ValueError("Property video aspect must be auto, 9:16 or 16:9")
    from PIL import Image
    landscape = 0
    portrait = 0
    for path in photo_paths:
        try:
            with Image.open(path) as image:
                if image.width >= image.height:
                    landscape += 1
                else:
                    portrait += 1
        except Exception:
            continue
    return "9:16" if portrait > landscape else "16:9"


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
    aspect_ratio: str = "9:16",
) -> bytes | str:
    """Render one scene through the project's existing provider transports."""
    engine = engine.strip().lower()
    log.info(
        "PROPERTY_VIDEO_PROVIDER_SUBMIT engine=%s paired=%s seconds=%s prompt_chars=%s",
        engine, bool(last_photo_path), int(seconds), len(prompt),
    )
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
            aspect_ratio=aspect_ratio,
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
            aspect_ratio,
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
        aspect=aspect_ratio,
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
    aspect_ratio: str = "9:16",
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
        aspect_ratio=aspect_ratio,
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


def assemble_property_video(
    scene_paths: list[str],
    output_path: str,
    duration: int,
    scene_durations: list[float] | None = None,
    aspect_ratio: str = "9:16",
) -> str:
    """Normalize, concatenate and trim scenes to one Telegram-safe MP4."""
    if not scene_paths:
        raise PropertyVideoError("No generated scenes to assemble")
    assembled = concatenate_mp4(
        scene_paths,
        output_path,
        durations=scene_durations,
        retime_to_fit=scene_durations is not None,
        aspect_ratio=aspect_ratio,
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
            "-crf", os.getenv("PROPERTY_VIDEO_FFMPEG_CRF", "20"), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(trimmed),
        ],
        check=True,
        capture_output=True,
        timeout=int(os.getenv("PROPERTY_VIDEO_FFMPEG_TIMEOUT_S", "600")),
    )
    trimmed.replace(target)
    return str(target)


def inspect_property_video(path: str, expected_duration: int, aspect_ratio: str) -> dict:
    """Run deterministic delivery checks without another provider request."""
    target = Path(path)
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name:format=duration,size",
        "-of", "json", str(target),
    ], check=True, capture_output=True, text=True, timeout=30)
    payload = json.loads(probe.stdout)
    stream = (payload.get("streams") or [{}])[0]
    fmt = payload.get("format") or {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration = float(fmt.get("duration") or 0)
    expected_size = (720, 1280) if aspect_ratio == "9:16" else (1280, 720)
    if (width, height) != expected_size:
        raise PropertyVideoError(f"Unexpected property video size: {width}x{height}")
    if abs(duration - float(expected_duration)) > 0.6:
        raise PropertyVideoError(f"Unexpected property video duration: {duration:.3f}s")

    from PIL import Image
    black_border_samples = 0
    sample_times = [max(0.1, duration * value) for value in (0.2, 0.5, 0.8)]
    for timestamp in sample_times:
        frame = subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-ss", f"{timestamp:.3f}",
            "-i", str(target), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
        ], check=True, capture_output=True, timeout=30).stdout
        image = Image.open(io.BytesIO(frame)).convert("RGB").resize((160, 90))
        pixels = image.load()
        top = [pixels[x, y] for y in range(4) for x in range(160)]
        bottom = [pixels[x, y] for y in range(86, 90) for x in range(160)]
        left = [pixels[x, y] for x in range(4) for y in range(90)]
        right = [pixels[x, y] for x in range(156, 160) for y in range(90)]
        dark = lambda band: sum(max(pixel) < 8 for pixel in band) / len(band)
        if (dark(top) > 0.96 and dark(bottom) > 0.96) or (dark(left) > 0.96 and dark(right) > 0.96):
            black_border_samples += 1
    if black_border_samples >= 2:
        raise PropertyVideoError("Final property video contains persistent black letterbox borders")
    return {
        "codec": str(stream.get("codec_name") or ""),
        "width": width,
        "height": height,
        "duration": round(duration, 3),
        "size": int(fmt.get("size") or target.stat().st_size),
        "black_border_samples": black_border_samples,
    }


def scene_manifest(scenes: list[PropertyScene]) -> list[dict]:
    return [asdict(scene) for scene in scenes]
