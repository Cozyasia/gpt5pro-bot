# -*- coding: utf-8 -*-
"""Read-only visual dump for the already-completed V265 one-shot verifier.

This module does not call Gemini, models, transfer code, delivery code, or quality gates.
It only reads the four already-persisted verifier artifacts from /data and emits compact
face crops so the completed production run can be visually inspected before cleanup.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
from pathlib import Path

_SENTINEL = Path("/data/v265_prod_verify_pr110_stability_quality_v1.once")
_ARTIFACT_DIR = Path("/data/v265_prod_verify_pr110_stability_quality_v1")
_EMITTED = False


def _face_crop(raw: bytes, *, source: bool) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as opened:
        image = opened.convert("RGB")
        if source:
            # Exact verifier fixture face area from the completed run, with generous head margin.
            crop = image.crop((735, 135, 1375, 955))
        else:
            # PERSON-A area from the completed 1856x2304 Stage-1/final frames.
            crop = image.crop((225, 650, 945, 1660))
        crop.thumbnail((170, 210), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (180, 220), "white")
        canvas.paste(crop, ((180 - crop.width) // 2, (220 - crop.height) // 2))
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=38, optimize=True)
        return out.getvalue()


def _emit_one(name: str, path: Path, *, source: bool) -> None:
    raw = path.read_bytes()
    encoded = _face_crop(raw, source=source)
    b64 = base64.b64encode(encoded).decode("ascii")
    print(
        f"AI_SELFIE_V265_SAVED_VISUAL name={name} jpeg_bytes={len(encoded)} b64={b64}",
        flush=True,
    )


def emit_saved_visuals_once() -> None:
    global _EMITTED
    if _EMITTED:
        return
    _EMITTED = True
    try:
        state = json.loads(_SENTINEL.read_text(encoding="utf-8"))
        if str(state.get("status", "")) != "completed":
            print(
                f"AI_SELFIE_V265_SAVED_VISUAL status=skipped sentinel_state={state.get('status', 'unknown')}",
                flush=True,
            )
            return
        items = (
            ("source", _ARTIFACT_DIR / "01_source_person_a.jpg", True),
            ("standard", _ARTIFACT_DIR / "04_standard_v265.png", False),
            ("strict", _ARTIFACT_DIR / "04_strict_v265.png", False),
            ("final", _ARTIFACT_DIR / "06_final_diagnostic_v265.png", False),
        )
        missing = [str(path) for _, path, _ in items if not path.exists()]
        if missing:
            print(
                "AI_SELFIE_V265_SAVED_VISUAL status=skipped reason=missing_artifacts missing=" + "|".join(missing),
                flush=True,
            )
            return
        for name, path, is_source in items:
            _emit_one(name, path, source=is_source)
        print("AI_SELFIE_V265_SAVED_VISUAL status=complete count=4 generation_calls=0", flush=True)
    except Exception as exc:
        print(
            f"AI_SELFIE_V265_SAVED_VISUAL status=failed error={type(exc).__name__}:{str(exc)[:500]}",
            flush=True,
        )


__all__ = ["emit_saved_visuals_once"]
