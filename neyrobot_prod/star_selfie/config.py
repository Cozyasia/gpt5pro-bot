from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class StarSelfieConfig:
    project_root: Path
    enabled: bool
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-image"
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1/models"
    face_swap_provider: str = "generic_rest"
    face_swap_api_key: str = ""
    face_swap_url: str = ""
    face_swap_result_path: str = "data.image"
    face_swap_auth_header: str = "Authorization"
    face_swap_auth_scheme: str = "Bearer"
    persistent_root: Path = Path("/data/star_selfie")
    seed_catalog_path: Path = Path("assets/star_selfie/catalog.json")
    request_timeout_s: int = 600
    max_generation_attempts: int = 2
    required_character_refs: int = 3
    max_character_refs: int = 6

    @classmethod
    def from_env(cls, project_root: Path) -> "StarSelfieConfig":
        return cls(
            project_root=project_root,
            enabled=_env_bool("STAR_SELFIE_ENABLED", False),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("STAR_SELFIE_GEMINI_MODEL", "gemini-3.1-flash-image"),
            gemini_api_base=os.getenv(
                "STAR_SELFIE_GEMINI_API_BASE",
                "https://generativelanguage.googleapis.com/v1/models",
            ),
            face_swap_provider=os.getenv("STAR_SELFIE_FACE_SWAP_PROVIDER", "generic_rest"),
            face_swap_api_key=os.getenv("STAR_SELFIE_FACE_SWAP_API_KEY", ""),
            face_swap_url=os.getenv("STAR_SELFIE_FACE_SWAP_URL", ""),
            face_swap_result_path=os.getenv("STAR_SELFIE_FACE_SWAP_RESULT_PATH", "data.image"),
            face_swap_auth_header=os.getenv("STAR_SELFIE_FACE_SWAP_AUTH_HEADER", "Authorization"),
            face_swap_auth_scheme=os.getenv("STAR_SELFIE_FACE_SWAP_AUTH_SCHEME", "Bearer"),
            persistent_root=Path(os.getenv("STAR_SELFIE_DATA_ROOT", "/data/star_selfie")),
            seed_catalog_path=Path(
                os.getenv("STAR_SELFIE_SEED_CATALOG", "assets/star_selfie/catalog.json")
            ),
            request_timeout_s=int(os.getenv("STAR_SELFIE_TIMEOUT_S", "600")),
            max_generation_attempts=int(os.getenv("STAR_SELFIE_MAX_ATTEMPTS", "2")),
        )

    def validate_runtime(self) -> None:
        if not self.enabled:
            return
        missing: list[str] = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.face_swap_url:
            missing.append("STAR_SELFIE_FACE_SWAP_URL")
        if missing:
            raise RuntimeError("Star Selfie is enabled but missing: " + ", ".join(missing))
