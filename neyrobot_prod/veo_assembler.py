"""FFmpeg assembly of independently generated native-audio Veo clips.

All inputs must be local, trusted job-owned files. Never interpolate user text
into filter graphs or shell commands. Caller handles billing and Telegram delivery.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path


def probe_duration(path: str | Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)], capture_output=True, text=True,
        check=True, timeout=30)
    return float(json.loads(proc.stdout)["format"]["duration"])


def assemble_vertical_video(
    clips: list[str | Path], destination: str | Path, duration_seconds: int,
    *, width: int = 720, height: int = 1280,
) -> Path:
    """Normalize A/V per clip, concatenate, then trim to exact requested length.

    Clip count and duration must match the timeline planner. FFmpeg preserves
    each scene's native speech; no additional audio synthesis is performed.
    """
    from .veo_multiscene import ALLOWED_DURATIONS, VEO_SCENE_SECONDS
    from math import ceil
    if duration_seconds not in ALLOWED_DURATIONS:
        raise ValueError("Unsupported duration")
    if len(clips) != ceil(duration_seconds / VEO_SCENE_SECONDS):
        raise ValueError("Clip count does not match planned duration")
    if width < 256 or height < 256 or width % 2 or height % 2:
        raise ValueError("Dimensions must be even and >=256")
    inputs = [Path(p).resolve() for p in clips]
    if not all(p.is_file() for p in inputs):
        raise FileNotFoundError("Missing input clip")
    if any(probe_duration(p) < min(7.5, duration_seconds) for p in inputs):
        raise ValueError("Input clip is too short")
    output = Path(destination).resolve()
    if output in inputs:
        raise ValueError("Output must not overwrite input")
    output.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1"]
    for path in inputs:
        args += ["-i", str(path)]
    filters = []
    for i in range(len(inputs)):
        filters.append(
            f"[{i}:v]fps=24,scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"trim=duration=8,setpts=PTS-STARTPTS,"
            f"fade=t=in:st=0:d=0.15,fade=t=out:st=7.85:d=0.15[v{i}]"
        )
        filters.append(
            f"[{i}:a]aresample=48000,atrim=duration=8,"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d=0.12,afade=t=out:st=7.88:d=0.12[a{i}]"
        )
    streams = "".join(f"[v{i}][a{i}]" for i in range(len(inputs)))
    filters.append(f"{streams}concat=n={len(inputs)}:v=1:a=1[v][a]")
    args += [
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", "[a]",
        "-t", str(duration_seconds),
        "-c:v", "libx264", "-threads:v", "1", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(output),
    ]
    try:
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or b"")[-4000:].decode("utf-8", "replace")
        raise RuntimeError(f"Veo FFmpeg assembly failed: {details}") from exc
    if abs(probe_duration(output) - duration_seconds) > 0.15:
        raise RuntimeError("Output duration validation failed")
    return output
