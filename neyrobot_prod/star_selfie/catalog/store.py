from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..errors import CatalogError
from ..models import Character
from .schema import character_from_dict, character_to_dict


class CharacterCatalog:
    def __init__(self, catalog_path: Path, references_root: Path):
        references_root = references_root.resolve()
        persistent_path = references_root.parent / "catalog.json"
        seed_path = catalog_path.resolve()

        # Repository assets are immutable deployment seeds. Runtime mutations must
        # survive redeploys in the same persistent root as character references.
        if seed_path != persistent_path.resolve():
            persistent_path.parent.mkdir(parents=True, exist_ok=True)
            if not persistent_path.exists() and seed_path.is_file():
                temp_path = persistent_path.with_suffix(".json.tmp")
                shutil.copy2(seed_path, temp_path)
                temp_path.replace(persistent_path)
            catalog_path = persistent_path

        self.catalog_path = catalog_path
        self.references_root = references_root

    def load(self) -> list[Character]:
        if not self.catalog_path.exists():
            return []
        try:
            raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Cannot read character catalog: {exc}") from exc
        return [
            character_from_dict(slug, item, self.references_root)
            for slug, item in raw.get("characters", {}).items()
        ]

    def active(self) -> list[Character]:
        return [character for character in self.load() if character.active]

    def get(self, slug: str) -> Character | None:
        normalized = slug.strip().lower()
        return next(
            (
                character
                for character in self.load()
                if character.slug == normalized
                or normalized in {alias.lower() for alias in character.aliases}
            ),
            None,
        )

    def save(self, characters: list[Character]) -> None:
        payload = {
            "schema_version": 1,
            "characters": {
                item.slug: character_to_dict(item, self.references_root)
                for item in sorted(characters, key=lambda value: value.slug)
            },
        }
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.catalog_path.with_suffix(self.catalog_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.catalog_path)
