from __future__ import annotations

import shutil
from pathlib import Path

from ..config import StarSelfieConfig
from .store import CharacterCatalog


def runtime_catalog(config: StarSelfieConfig) -> CharacterCatalog:
    """Return the persistent catalog, seeding it once from repository assets."""
    runtime_path = config.persistent_root / "catalog.json"
    seed_path = config.seed_catalog_path
    if not seed_path.is_absolute():
        seed_path = config.project_root / seed_path

    if not runtime_path.exists():
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        if seed_path.is_file():
            temp = runtime_path.with_suffix(".json.tmp")
            shutil.copy2(seed_path, temp)
            temp.replace(runtime_path)

    return CharacterCatalog(runtime_path, config.persistent_root / "references")


__all__ = ["runtime_catalog"]
