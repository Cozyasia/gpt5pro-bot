"""Public diagnostic comparison: source/A/T/H, crops plus full scenes."""

import argparse, json
from pathlib import Path
import cv2
from PIL import Image, ImageDraw, ImageFont
from scripts.v265_transfer_matrix import pointset
from scripts.v265_matrix_sheets import review_crop


def run(a):
    cv2.setNumThreads(1)
    a.destination.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
    sheet = Image.new("RGB", (1280, 3 * 845), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for row, case in enumerate(("case01", "case02", "case04")):
        for col, mode in enumerate(
            ("source", "A_baseline", "T_exact_field", "H_jaw_silhouette")
        ):
            path = (
                a.fixtures / (case + "_source.jpg")
                if mode == "source"
                else a.output / case / (mode + "_selected.png")
            )
            im = cv2.imread(str(path))
            _, _, p = pointset(im, a.models, col > 0)
            crop, _ = review_crop(im, p)
            x, y = col * 320, row * 845
            draw.text((x + 6, y + 7), case + " | " + mode, fill="black", font=font)
            sheet.paste(
                Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)), (x, y + 35)
            )
            context = Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
            context.thumbnail((310, 385))
            sheet.paste(context, (x + (320 - context.width) // 2, y + 442))
            draw.text(
                (x + 6, y + 823), "DIAGNOSTIC - NOT APPROVED", fill="#900000", font=font
            )
    sheet.save(a.destination / "shape_diagnostic_comparison.jpg", quality=92)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--destination", type=Path, required=True)
    run(p.parse_args())
