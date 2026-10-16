"""Extract exact original Suno audio excerpts for an audio-driven video provider.

This module does not imply that Seedance accepts an audio reference.
Only pass excerpts to a provider with verified audio-driven lip-sync support.
"""
from __future__ import annotations

from pathlib import Path
import subprocess


def extract_suno_excerpt(audio_path: str, output_path: str, *, start_s: float,
                         end_s: float, timeout_s: int = 120) -> str:
    """Decode a time interval to PCM WAV to avoid compressed-frame seek drift."""
    source = Path(audio_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError("Suno audio file is missing")
    if start_s < 0 or end_s <= start_s or end_s - start_s > 60:
        raise ValueError("invalid audio interval")
    if timeout_s <= 0:
        raise ValueError("timeout must be positive")
    if output.suffix.lower() != ".wav":
        raise ValueError("excerpt output must be WAV")
    if source.resolve() == output.resolve():
        raise ValueError("cannot overwrite original Suno audio")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-ss", f"{start_s:.3f}", "-t", f"{end_s - start_s:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=timeout_s)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("FFmpeg returned no Suno excerpt")
    return str(output)
