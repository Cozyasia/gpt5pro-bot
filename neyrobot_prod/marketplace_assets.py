"""Deterministic post-processing for marketplace deliverables."""
from __future__ import annotations

import io
import textwrap

from PIL import Image, ImageDraw, ImageFont


_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)


def _font(size: int):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _brief_lines(brief: str) -> list[str]:
    """Use only seller-confirmed text; normalize and cap it for readability."""
    normalized = " ".join(str(brief or "").split())
    if not normalized:
        raise ValueError("Для инфографики нужен подтверждённый текст.")
    return textwrap.wrap(normalized, width=32, break_long_words=False)[:7]


def build_infographic(source_png: bytes, confirmed_brief: str) -> bytes:
    """Overlay Cyrillic text locally so the image model cannot mistranscribe it."""
    try:
        source = Image.open(io.BytesIO(source_png)).convert("RGBA")
    except Exception as exc:
        raise ValueError("Не удалось подготовить основу инфографики.") from exc
    source = source.resize((1024, 1024), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((500, 70, 980, 954), radius=32, fill=(255, 255, 255, 235))
    draw.text((548, 120), "Характеристики", font=_font(38), fill=(24, 24, 28, 255))
    y = 205
    body = _font(30)
    for line in _brief_lines(confirmed_brief):
        draw.ellipse((540, y + 10, 552, y + 22), fill=(109, 65, 210, 255))
        draw.text((572, y), line, font=body, fill=(34, 34, 38, 255))
        y += 82
    result = Image.alpha_composite(source, overlay).convert("RGB")
    output = io.BytesIO()
    result.save(output, format="PNG", optimize=True)
    return output.getvalue()
