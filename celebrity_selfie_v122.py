# -*- coding: utf-8 -*-
# Auto-generated compact loader for Celebrity Selfie v122.
from pathlib import Path
import base64
import json
import zlib

_ROOT = Path(__file__).resolve().parent
_LIBRARY = _ROOT / "celebrity_library"
_PAYLOAD = _ROOT / "celebrity_selfie_v122_payload"


def _materialize_catalog(country: str) -> None:
    """Build the runtime JSON catalog from the compact, reviewable TSV source."""
    source = _LIBRARY / f"catalog_{country}_v1.tsv"
    target = _LIBRARY / f"catalog_{country}_v1.json"
    entries = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        celeb_id, display_name, sort_name, aliases_json = line.split("\t", 3)
        entries.append({
            "id": celeb_id,
            "country": country,
            "display_name": display_name,
            "sort_name": sort_name,
            "aliases": json.loads(aliases_json),
            "category": "",
            "wikipedia": {},
            "enabled": True,
        })
    target.write_text(
        json.dumps(
            {
                "version": "v1-2026-07-19",
                "country": country,
                "celebrities": entries,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


for _country in ("ru", "us"):
    _materialize_catalog(_country)

_encoded = "".join(
    (_PAYLOAD / name).read_text(encoding="ascii")
    for name in ("part_01.txt", "part_02.txt", "part_03.txt", "part_04.txt")
)
exec(compile(zlib.decompress(base64.b85decode(_encoded)), __file__, "exec"))
