"""Persistent scene artifacts for resumable Veo jobs.

Files are written atomically under an explicit job directory. The caller must
serialize writes for the same job and ensure its directory is on persistent disk.
"""
from __future__ import annotations
import os
import tempfile
from pathlib import Path


def scene_file(job_directory: str | Path, index: int) -> Path:
    if index < 1:
        raise ValueError("Scene index must be positive")
    return Path(job_directory) / f"scene_{index:02d}.mp4"


def save_scene(job_directory: str | Path, index: int, video: bytes) -> Path:
    if not isinstance(video, bytes) or len(video) < 1024:
        raise ValueError("Scene video must contain at least 1024 bytes")
    destination = scene_file(job_directory, index)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".scene-", suffix=".mp4", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(video)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return destination


def load_scene(job_directory: str | Path, index: int) -> bytes:
    path = scene_file(job_directory, index)
    result = path.read_bytes()
    if len(result) < 1024:
        raise ValueError("Persisted scene is empty or truncated")
    return result


def list_complete_scenes(job_directory: str | Path, count: int) -> list[Path]:
    if count < 1:
        raise ValueError("Scene count must be positive")
    files = [scene_file(job_directory, i) for i in range(1, count + 1)]
    for path in files:
        if not path.is_file() or path.stat().st_size < 1024:
            raise FileNotFoundError(f"Missing or incomplete scene: {path.name}")
    return files
