"""Safe real-estate video assembly helpers (no paid provider calls)."""
from __future__ import annotations
import asyncio
from pathlib import Path
import subprocess


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


def concatenate_mp4(clips: list[str], output: str) -> str:
    """Normalize each scene and concat through FFmpeg; no shell interpolation."""
    if not clips:
        raise ValueError("No clips supplied")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    for i, clip in enumerate(clips):
        source = Path(clip).resolve(strict=True)
        intermediate = target.parent / f"normalized_{i:03d}.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-i", str(source),
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,"
                   "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(intermediate)
        ], check=True, capture_output=True, timeout=240)
        normalized.append(intermediate)
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
