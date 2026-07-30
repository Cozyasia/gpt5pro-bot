from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from neyrobot_prod.star_selfie.admin import is_admin
from neyrobot_prod.star_selfie.catalog.store import CharacterCatalog
from neyrobot_prod.star_selfie.models import Character


def test_admin_ids_are_explicit(monkeypatch):
    monkeypatch.setenv("STAR_SELFIE_ADMIN_IDS", "101, 202")
    monkeypatch.delenv("OWNER_ID", raising=False)

    assert is_admin(SimpleNamespace(id=101)) is True
    assert is_admin(SimpleNamespace(id=999)) is False


def test_catalog_is_seeded_into_persistent_root(tmp_path: Path):
    seed = tmp_path / "repo" / "assets" / "catalog.json"
    seed.parent.mkdir(parents=True)
    seed.write_text(
        json.dumps({
            "schema_version": 1,
            "characters": {
                "seed": {
                    "title": "Seed Hero",
                    "aliases": [],
                    "active": False,
                    "source": "seed",
                    "references": [],
                }
            },
        }),
        encoding="utf-8",
    )
    references = tmp_path / "data" / "references"
    catalog = CharacterCatalog(seed, references)

    assert catalog.catalog_path == tmp_path / "data" / "catalog.json"
    assert catalog.get("seed") is not None

    catalog.save([
        Character(slug="runtime", title="Runtime Hero", active=False, reference_paths=[])
    ])
    assert "runtime" in catalog.catalog_path.read_text(encoding="utf-8")
    assert "runtime" not in seed.read_text(encoding="utf-8")
