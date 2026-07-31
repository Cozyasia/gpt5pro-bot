from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True, slots=True)
class StarSelfieConfig:
    project_root: Path
    enabled: bool
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-image"
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1/models"
    face_swap_provider: str = "segmind"
    face_swap_api_key: str = ""
    face_swap_url: str = "https://api.segmind.com/v1/faceswap-v2"
    face_swap_result_path: str = "data.image"
    face_swap_auth_header: str = "Authorization"
    face_swap_auth_scheme: str = "Bearer"
    segmind_face_restore: str = "codeformer-v0.1.0.pth"
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
            gemini_api_key=_first_env("STAR_SELFIE_GEMINI_API_KEY", "GEMINI_IMAGE_API_KEY", "GEMINI_API_KEY"),
            gemini_model=os.getenv(
                "STAR_SELFIE_GEMINI_MODEL",
                os.getenv("GEMINI_IMAGE_FALLBACK_MODEL", "gemini-3.1-flash-image"),
            ),
            gemini_api_base=os.getenv(
                "STAR_SELFIE_GEMINI_API_BASE",
                "https://generativelanguage.googleapis.com/v1/models",
            ),
            face_swap_provider=os.getenv("STAR_SELFIE_FACE_SWAP_PROVIDER", "segmind").strip().lower(),
            face_swap_api_key=_first_env("STAR_SELFIE_FACE_SWAP_API_KEY", "SEGMIND_API_KEY"),
            face_swap_url=os.getenv(
                "STAR_SELFIE_FACE_SWAP_URL",
                "https://api.segmind.com/v1/faceswap-v2",
            ),
            face_swap_result_path=os.getenv("STAR_SELFIE_FACE_SWAP_RESULT_PATH", "data.image"),
            face_swap_auth_header=os.getenv("STAR_SELFIE_FACE_SWAP_AUTH_HEADER", "Authorization"),
            face_swap_auth_scheme=os.getenv("STAR_SELFIE_FACE_SWAP_AUTH_SCHEME", "Bearer"),
            segmind_face_restore=os.getenv(
                "STAR_SELFIE_SEGMIND_FACE_RESTORE",
                os.getenv("SEGMIND_FACE_RESTORE", "codeformer-v0.1.0.pth"),
            ),
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
            missing.append("GEMINI_IMAGE_API_KEY")
        if not self.face_swap_api_key:
            missing.append("SEGMIND_API_KEY")
        if not self.face_swap_url:
            missing.append("STAR_SELFIE_FACE_SWAP_URL")
        if self.face_swap_provider not in {"segmind", "generic_rest"}:
            raise RuntimeError(f"Unsupported Star Selfie Face Swap provider: {self.face_swap_provider}")
        if missing:
            raise RuntimeError("Star Selfie is enabled but missing: " + ", ".join(missing))
