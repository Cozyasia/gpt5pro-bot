from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StarSelfieConfig:
    project_root: Path
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash-image"
    face_swap_provider: str = "piapi"
    face_swap_api_key: str = ""
    persistent_root: Path = Path("/data/star_selfie")
    seed_catalog_path: Path = Path("assets/star_selfie/catalog.json")
    request_timeout_s: int = 600
    max_generation_attempts: int = 2
    required_character_refs: int = 3
    max_character_refs: int = 6
