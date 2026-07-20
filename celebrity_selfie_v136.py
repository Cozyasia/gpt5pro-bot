# -*- coding: utf-8 -*-
"""Compact production loader for Celebrity Selfie v136.

The reviewable behavior and configuration are documented in RELEASE_V136.md.
The payload is split only to keep GitHub connector writes reliable; execution is
identical to the compiled UTF-8 source and its SHA-256 is checked before exec.
"""
from pathlib import Path
import base64
import hashlib
import zlib

_ROOT = Path(__file__).resolve().parent
_PAYLOAD = _ROOT / "celebrity_selfie_v136_payload"
_PARTS = tuple(sorted(_PAYLOAD.glob("part_*.txt")))
_SOURCE_SHA256 = "a1e76e6328da3ce6ee06acb7d8a30b01ae976a7e17bad2a59919856d6c3199e2"
_encoded = "".join(path.read_text(encoding="ascii") for path in _PARTS)
_source = zlib.decompress(base64.b85decode(_encoded))
if hashlib.sha256(_source).hexdigest() != _SOURCE_SHA256:
    raise RuntimeError("Celebrity Selfie v136 payload checksum mismatch")
exec(compile(_source, __file__, "exec"))
