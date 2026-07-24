# -*- coding: utf-8 -*-
"""Validated high-resolution owner reference loader for v161.

The repository contents API transports the JPEG as deterministic ASCII chunks.
This module reconstructs and verifies the complete asset before replacing only
reference 01. References 02 and 03 remain the validated owner-provided fallback
copies until their high-resolution chunks are added.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from PIL import Image

import celebrity_selfie_v158 as reference_release
from . import hotfix_v161 as release

_INSTALLED = False


def _decode_chunks(directory: Path, index: int) -> str | None:
    chunks = sorted(directory.glob("chunk_*.txt"))
    if not chunks:
        return None
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in chunks)
    raw = base64.b64decode(encoded, validate=True)
    if not (len(raw) >= 20_000 and raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")):
        raise ValueError(f"owner reference {index} is not a complete high-resolution JPEG")
    with Image.open(Path(directory) / "_virtual.jpg" if False else __import__("io").BytesIO(raw)) as image:
        image.verify()
        width, height = image.size
    if min(width, height) < 400:
        raise ValueError(f"owner reference {index} is too small: {width}x{height}")
    return release._cache_reference(raw, index)


def _full_reference_paths_v2() -> list[str]:
    fallback = list(release._V158_FIXED_PATHS() or [])
    if len(fallback) != 3:
        raise RuntimeError("Roman reference fallback pack must contain exactly three images")
    result: list[str] = []
    for index, fallback_path in enumerate(fallback, start=1):
        directory = reference_release._PACK_ROOT / "full_v2" / f"{index:02d}"
        upgraded = _decode_chunks(directory, index)
        result.append(upgraded or fallback_path)
    if len(result) != 3 or len(set(result)) != 3:
        raise RuntimeError("Roman reference pack did not materialise as three unique files")
    return result


def install() -> bool:
    global _INSTALLED
    release._decode_full_parts = _decode_chunks
    release._full_reference_paths = _full_reference_paths_v2
    reference_release._fixed_reference_paths = _full_reference_paths_v2
    paths = _full_reference_paths_v2()
    _INSTALLED = len(paths) == 3
    return _INSTALLED


install()

__all__ = ["install", "_decode_chunks", "_full_reference_paths_v2"]
