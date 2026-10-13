"""Fail-closed preflight for the optional Veo 24s + Kling lip-sync path.

Pure validation: never submits or charges provider tasks.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from .veo_multiscene import plan_video


@dataclass(frozen=True)
class VoiceScene:
    index: int
    start_seconds: int
    end_seconds: int
    video_path: Path
    audio_path: Path


def validate_voice_scenes(job_directory: str | Path, spoken_script: str) -> tuple[VoiceScene, ...]:
    """Require all three complete video clips and matching 8s TTS slices.

    A caller must not invoke paid lip-sync if any prerequisite is missing.
    """
    directory = Path(job_directory).resolve()
    scenes = plan_video(24, spoken_script)
    if len(scenes) != 3:
        raise ValueError("24-second voice workflow requires exactly three scenes")
    master = directory / "tts_master.wav"
    if not master.is_file() or master.stat().st_size < 1024:
        raise FileNotFoundError("One continuous TTS master is required")
    result = []
    for scene in scenes:
        video = directory / f"scene_{scene.index:02d}.mp4"
        audio = directory / f"tts_scene_{scene.index:02d}.wav"
        for path in (video, audio):
            if not path.is_file() or path.stat().st_size < 1024:
                raise FileNotFoundError(f"Required voice scene input missing: {path.name}")
        result.append(VoiceScene(scene.index, scene.timeline_start, scene.timeline_end, video, audio))
    return tuple(result)
