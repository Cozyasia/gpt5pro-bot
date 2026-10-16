"""Safe FFmpeg assembly of rendered singing clips with original Suno audio.

Inputs are local, trusted downloaded files. Never shell-interpolate user strings.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

def assemble_singing_clip(video_segments: list[str], audio_path: str, output_path: str, *, timeout: int = 900) -> str:
    if not video_segments:
        raise ValueError("at least one video segment required")
    paths = [Path(p) for p in video_segments]
    audio = Path(audio_path)
    output = Path(output_path)
    if not all(p.is_file() for p in paths) or not audio.is_file():
        raise FileNotFoundError("missing video segment or Suno audio")
    if output.resolve() in {p.resolve() for p in paths} | {audio.resolve()}:
        raise ValueError("output must not overwrite inputs")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Normalize segment timestamps, codecs, frame rate and dimensions to 720x1280.
    # This avoids concat failures when provider outputs differ.
    filters = []
    for i in range(len(paths)):
        filters.append(
            f"[{i}:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[v{i}]"
        )
    joined = "".join(f"[v{i}]" for i in range(len(paths)))
    filters.append(f"{joined}concat=n={len(paths)}:v=1:a=0[vout]")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for p in paths:
        cmd.extend(["-i", str(p)])
    cmd.extend(["-i", str(audio), "-filter_complex", ";".join(filters),
                "-map", "[vout]", "-map", f"{len(paths)}:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                str(output)])
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("ffmpeg did not produce a valid output file")
    return str(output)
