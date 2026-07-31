from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class CaptureMode(StrEnum):
    THIRD_PERSON = "third_person"
    TRUE_PHONE_SELFIE = "true_phone_selfie"


@dataclass(slots=True)
class Character:
    slug: str
    title: str
    aliases: list[str] = field(default_factory=list)
    active: bool = False
    reference_paths: list[Path] = field(default_factory=list)
    source: str = "restored"


@dataclass(slots=True)
class GenerationRequest:
    user_id: int
    user_face_path: Path
    user_body_path: Path
    character: Character
    scene: str
    capture_mode: CaptureMode
    aspect_ratio: str = "4:5"
    scene_reference_path: Path | None = None


@dataclass(slots=True)
class GenerationResult:
    scene_image_path: Path
    final_image_path: Path
    capture_mode: CaptureMode
    scene_provider: str
    face_swap_provider: str
    metadata: dict[str, object] = field(default_factory=dict)
