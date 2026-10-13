"""Offline audio timeline utilities for 24-second Veo shorts.

No network calls or paid provider operations. All clips use a single TTS master.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def split_tts_master(master: str | Path, output_directory: str | Path, *, seconds: int = 24) -> list[Path]:
    """Cut one continuous voice track into exact 8-second WAV slices.

    Do not synthesize each scene independently: that can change the voice.
    """
    if seconds != 24:
        raise ValueError("The three-scene voice timeline must be 24 seconds")
    source = Path(master).resolve()
    if not source.is_file():
        raise FileNotFoundError("TTS master audio not found")
    destination = Path(output_directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, start in enumerate((0, 8, 16), start=1):
        target = destination / f"tts_scene_{index:02d}.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-y",
             "-i", str(source), "-ss", str(start), "-t", "8",
             "-af", "aresample=48000,apad=whole_dur=8,atrim=duration=8",
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
             str(target)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120,
        )
        outputs.append(target)
    return outputs


def mux_master_voice(video: str | Path, master: str | Path, output: str | Path) -> Path:
    """Replace independently generated scene audio with one continuous voice track."""
    video_path, audio_path, target = Path(video).resolve(), Path(master).resolve(), Path(output).resolve()
    if not video_path.is_file() or not audio_path.is_file():
        raise FileNotFoundError("Video and TTS master must exist")
    if target in (video_path, audio_path):
        raise ValueError("Output cannot overwrite inputs")
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(video_path),
         "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
         "-t", "24", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-af", "apad=whole_dur=24,atrim=duration=24",
         "-movflags", "+faststart", str(target)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180,
    )
    return target
