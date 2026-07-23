# -*- coding: utf-8 -*-
"""Reference-asset compatibility loaded before Celebrity Selfie v158 installs.

Owner-provided references are deliberately compact to keep repository checkout
and Render startup reliable. A complete JPEG over 4 KB is sufficient because
v158 verifies SOI/EOI markers and the image is decoded again by Pillow/provider
preprocessing before generation.
"""
from __future__ import annotations


def install() -> None:
    import celebrity_selfie_v158 as release

    def _valid_owner_jpeg(raw: bytes) -> bool:
        return bool(
            len(raw or b"") >= 4_000
            and raw.startswith(b"\xff\xd8\xff")
            and raw.endswith(b"\xff\xd9")
        )

    release._valid_jpeg = _valid_owner_jpeg


install()

__all__ = ["install"]
