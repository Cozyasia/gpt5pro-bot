# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_v156_source_is_valid_python() -> None:
    ast.parse(_source("celebrity_selfie_v156.py"))


def test_v156_blocks_obsolete_media_routes() -> None:
    source = _source("celebrity_selfie_v156.py")
    assert 'CELEBRITY_V142_LOCAL_REMBG_FALLBACK"] = "0"' in source
    assert 'CELEBRITY_V142_LEGACY_FALLBACK"] = "0"' in source
    assert "photoroom_composite=disabled" in source
    assert "direct_gemini=disabled" in source
    assert "piapi=disabled" in source
    assert "face_swap=disabled" in source


def test_v156_has_reference_and_anti_wax_quality_gates() -> None:
    source = _source("celebrity_selfie_v156.py")
    assert "_rank_celebrity_references" in source
    assert "wax_or_exhibit" in source
    assert "no_plaque_poster_or_museum_display" in source
    assert "exactly_two_main_adults" in source
    assert "targeted_weak_side_repair" in source


def test_startup_activates_only_current_selfie_overlay() -> None:
    site = _source("sitecustomize.py")
    versioning = _source("neyrobot_prod/versioning.py")
    package = _source("neyrobot_prod/__init__.py")
    assert "celebrity_selfie_v156" in site
    assert "celebrity_selfie_v154" not in site
    assert "memory_safety_v155" not in site
    assert "celebrity_selfie_v156" in versioning
    assert "install_v154" not in versioning
    for obsolete in range(136, 155):
        assert f"from celebrity_selfie_v{obsolete} import" not in package


def test_version_contract_points_to_v156() -> None:
    expected = "v156-comet-dual-identity-best-of-n-2026-07-23"
    assert expected in _source("celebrity_selfie_v156.py")
    assert expected in _source("neyrobot_prod/versioning.py")
    assert expected in _source("neyrobot_prod/__init__.py")
