from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import Character


def character_from_dict(slug: str, raw: dict[str, Any], root: Path) -> Character:
    return Character(
        slug=slug,
        title=str(raw.get("title") or slug),
        aliases=[str(x) for x in raw.get("aliases", [])],
        active=bool(raw.get("active", False)),
        reference_paths=[root / slug / str(x) for x in raw.get("references", [])],
        source=str(raw.get("source") or "restored"),
    )


def character_to_dict(character: Character, references_root: Path) -> dict[str, Any]:
    references: list[str] = []
    character_root = references_root / character.slug
    for path in character.reference_paths:
        try:
            references.append(str(path.relative_to(character_root)))
        except ValueError:
            references.append(path.name)
    return {
        "title": character.title,
        "aliases": list(character.aliases),
        "active": character.active,
        "source": character.source,
        "references": references,
    }
