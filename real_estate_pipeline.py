"""Safe real-estate video assembly helpers (no paid provider calls)."""
from __future__ import annotations
import asyncio
from pathlib import Path
import subprocess
import os


def plan_shots(photo_ids: list[str], duration: int) -> list[dict]:
    """Allocate at least one distinct image per shot without inventing floor plans."""
    if not photo_ids or duration <= 0:
        raise ValueError("At least one photo and a positive duration are required")
    count = min(len(photo_ids), max(1, duration // 5))
    base, remainder = divmod(duration, count)
    return [
        {"photo_id": photo_ids[i], "seconds": base + (i < remainder), "shot_index": i}
        for i in range(count)
    ]


def _audio_tempo_filters(factor: float) -> str:
    """Build atempo filters for any positive playback speed."""
    if factor <= 0:
        raise ValueError("Playback speed must be positive")
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.8f}")
    return ",".join(filters)


def concatenate_mp4(
    clips: list[str],
    output: str,
    durations: list[float] | None = None,
    *,
    retime_to_fit: bool = False,
    aspect_ratio: str = "9:16",
) -> str:
    """Normalize each scene and concat through FFmpeg; no shell interpolation."""
    if not clips:
        raise ValueError("No clips supplied")
    if durations is not None and len(durations) != len(clips):
        raise ValueError("Scene duration count must match clip count")
    if aspect_ratio == "9:16":
        width, height = 720, 1280
    elif aspect_ratio == "16:9":
        width, height = 1280, 720
    else:
        raise ValueError("Output aspect ratio must be 9:16 or 16:9")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    crossfade = 0.0
    if durations is not None and len(clips) > 1:
        crossfade = max(0.0, min(float(os.getenv("PROPERTY_VIDEO_CROSSFADE_S", "0.12")), 0.35))
    for i, clip in enumerate(clips):
        source = Path(clip).resolve(strict=True)
        intermediate = target.parent / f"normalized_{i:03d}.mp4"
        # Fill the delivery canvas. Padding created 62.5% black pixels in a
        # real property test and made the result look like a cheap slideshow.
        video_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        video_filter += f"crop={width}:{height},setsar=1,fps=30"
        audio_filter = None
        if retime_to_fit and durations is not None:
            target_duration = float(durations[i])
            if target_duration <= 0:
                raise ValueError("Scene durations must be positive")
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(source),
            ], check=True, capture_output=True, text=True, timeout=30)
            source_duration = float(probe.stdout.strip())
            if source_duration <= 0:
                raise ValueError(f"Clip has no positive duration: {source}")
            playback_speed = source_duration / target_duration
            video_filter = f"setpts=PTS/{playback_speed:.10f}," + video_filter
            streams = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(source),
            ], check=True, capture_output=True, text=True, timeout=30)
            if streams.stdout.strip():
                audio_filter = _audio_tempo_filters(playback_speed)
        if crossfade and i < len(clips) - 1:
            # Hold the exact terminal reference briefly so the next clip can
            # blend from the same shared route frame without shortening the
            # requested final duration.
            video_filter += f",tpad=stop_mode=clone:stop_duration={crossfade:.3f}"
        render_duration = None
        if durations is not None:
            render_duration = float(durations[i]) + (crossfade if i < len(clips) - 1 else 0.0)
        command = [
            "ffmpeg", "-nostdin", "-y", "-i", str(source),
            *(["-t", f"{render_duration:.3f}"] if render_duration is not None else []),
            "-vf", video_filter,
            *(["-af", audio_filter] if audio_filter else []),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(intermediate)
        ]
        subprocess.run(command, check=True, capture_output=True, timeout=240)
        normalized.append(intermediate)
    if crossfade:
        command = ["ffmpeg", "-nostdin", "-y"]
        for path in normalized:
            command.extend(["-i", str(path)])
        filters = []
        previous = "0:v"
        offset = float(durations[0])
        for index in range(1, len(normalized)):
            output_label = f"xf{index}"
            filters.append(
                f"[{previous}][{index}:v]xfade=transition=fade:duration={crossfade:.3f}:"
                f"offset={offset:.3f}[{output_label}]"
            )
            previous = output_label
            offset += float(durations[index])
        command.extend([
            "-filter_complex", ";".join(filters), "-map", f"[{previous}]", "-an",
            "-c:v", "libx264", "-preset", os.getenv("PROPERTY_VIDEO_FFMPEG_PRESET", "veryfast"),
            "-crf", os.getenv("PROPERTY_VIDEO_FFMPEG_CRF", "20"), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(target),
        ])
        subprocess.run(command, check=True, capture_output=True, timeout=240)
        return str(target)
    manifest = target.parent / "concat_manifest.txt"
    manifest.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in normalized))
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
        "-i", str(manifest), "-c", "copy", "-movflags", "+faststart", str(target)
    ], check=True, capture_output=True, timeout=240)
    return str(target)


async def fetch_telegram_photos(bot, photo_ids: list[str], directory: str) -> list[str]:
    """Resolve Telegram file IDs using the bot's own authenticated file endpoint."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, file_id in enumerate(photo_ids):
        remote = await bot.get_file(file_id)
        destination = folder / f"reference_{i:03d}.jpg"
        await remote.download_to_drive(custom_path=str(destination))
        paths.append(str(destination))
    return paths
