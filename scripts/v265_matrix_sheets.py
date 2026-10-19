"""Render public-only frozen comparisons; no human acceptance is inferred."""

import argparse, json
from pathlib import Path
import cv2
from PIL import Image, ImageDraw, ImageFont
from scripts.v265_transfer_matrix import pointset
from neyrobot_prod.v265_source_fidelity import canonical_crop, normalize, eye_frame


def review_crop(image, points):
    m = eye_frame(points) * 130
    m[:, 2] += [160, 100]
    return cv2.warpAffine(image, m, (320, 400)), None


def run(a):
    cv2.setNumThreads(1)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    a.destination.mkdir(parents=True, exist_ok=True)
    for case in ["case01", "case02", "case04"]:
        base = a.output / case
        if not (base / "D_mask_core.json").exists():
            continue
        source = cv2.imread(str(a.fixtures / (case + "_source.jpg")))
        _, _, sp = pointset(source, a.models)
        entries = [
            ("Source", source, sp),
            ("Frozen Stage-1", cv2.imread(str(base / "stage1.png")), None),
        ]
        for mode in [
            "A_baseline",
            "B_mask",
            "C_core",
            "D_mask_core",
            "E_mask_frequency",
        ]:
            entries.append(
                (mode, cv2.imread(str(base / (mode + "_selected.png"))), None)
            )
        sheet = Image.new("RGB", (7 * 320, 700), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        for col, (label, im, pts) in enumerate(entries):
            if pts is None:
                _, _, pts = pointset(im, a.models, True)
            crop, _ = canonical_crop(im, pts)
            sheet.paste(
                Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)), (col * 320, 40)
            )
            draw.text((col * 320 + 8, 10), label, fill="black", font=font)
            context = Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
            context.thumbnail((205, 250))
            sheet.paste(context, (col * 320 + 50, 445))
            # Source green / candidate magenta in the SAME global eye frame.
            overlay = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            od = ImageDraw.Draw(overlay)
            for points, color in [(sp, "#00ff88"), (pts, "#ff00bb")]:
                q = normalize(points) * 160 + [160, 120]
                for x, y in q:
                    od.ellipse((x - 1, y - 1, x + 1, y + 1), fill=color)
            overlay.save(
                a.destination / (case + "_" + label.replace(" ", "_") + "_overlay.png")
            )
        sheet.save(a.destination / (case + "_all_variants.jpg"), quality=94)
    # Compact review: original plus baseline / planar / frequency. Three cases.
    sheet = Image.new("RGB", (1280, 3 * 465 + 42), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    labels = [
        "Source",
        "A: baseline",
        "B: mask + planar core",
        "C: mask + frequency core",
    ]
    for col, label in enumerate(labels):
        draw.text((col * 320 + 6, 8), label, fill="black", font=font)
    for row, case in enumerate(["case01", "case02", "case04"]):
        for col, mode in enumerate(
            [None, "A_baseline", "D_mask_core", "E_mask_frequency"]
        ):
            path = (
                a.fixtures / (case + "_source.jpg")
                if mode is None
                else a.output / case / (mode + "_selected.png")
            )
            im = cv2.imread(str(path))
            _, _, p = pointset(im, a.models, col > 0)
            crop, _ = review_crop(im, p)
            sheet.paste(
                Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)),
                (320 * col, 42 + row * 465),
            )
            draw.text(
                (320 * col + 8, 445 + row * 465),
                case + " | not human-approved",
                fill="black",
                font=font,
            )
    sheet.save(a.destination / "human_comparison.jpg", quality=95)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    run(p.parse_args())
