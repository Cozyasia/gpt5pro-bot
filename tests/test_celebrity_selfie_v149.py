# -*- coding: utf-8 -*-
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

import celebrity_selfie_v149 as v149


def _jpeg(width=800, height=1000, rectangle=None):
    image = Image.new("RGB", (width, height), (55, 65, 78))
    if rectangle:
        draw = ImageDraw.Draw(image)
        draw.rectangle(rectangle, fill=(220, 150, 95))
    out = BytesIO()
    image.save(out, "JPEG", quality=96)
    return out.getvalue()


def _placement(x=420, y=180, w=320, h=700):
    return {
        "position": [x, y],
        "size": [w, h],
        "alpha_metrics": {
            "bbox": [4, 3, w - 4, h - 3],
            "coverage": 0.38,
            "transparent": 0.55,
            "border_opaque": 0.08,
            "transparent_corners": 4,
        },
    }


def _cutout(with_face=True):
    image = Image.new("RGBA", (320, 700), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 30, 250, 230), fill=(180, 130, 105, 255))
    draw.rectangle((55, 205, 265, 690), fill=(90, 105, 125, 255))
    return {
        "image": image,
        "face": {"x": 70.0, "y": 30.0, "w": 180.0, "h": 200.0} if with_face else None,
        "alpha_metrics": {
            "bbox": [55, 30, 265, 690],
            "coverage": 0.45,
            "transparent": 0.55,
            "border_opaque": 0.02,
            "transparent_corners": 4,
        },
    }


class CelebritySelfieV149Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v149.VERSION, "v149-visible-human-layer-proof-2026-07-21")

    def test_non_human_cutout_is_rejected(self):
        self.assertIn("no verified source face", v149._human_cutout_problem(_cutout(False), "celebrity"))

    def test_face_preserving_cutout_is_accepted(self):
        self.assertEqual(v149._human_cutout_problem(_cutout(True), "celebrity"), "")

    def test_pixel_delta_proves_visible_layer(self):
        before = _jpeg()
        after = _jpeg(rectangle=(450, 220, 710, 850))
        delta = v149._pixel_delta(before, after, _placement())
        self.assertGreater(delta["changed_ratio"], 0.10)
        self.assertGreater(delta["mean_delta"], 2.2)
        self.assertEqual(v149._delta_problem(delta, "celebrity"), "")

    def test_pixel_delta_rejects_metadata_only_layer(self):
        raw = _jpeg()
        delta = v149._pixel_delta(raw, raw, _placement())
        self.assertIn("not visibly present", v149._delta_problem(delta, "celebrity"))

    def test_final_builder_requires_both_pixel_deltas(self):
        source = Path("celebrity_selfie_v149.py").read_text(encoding="utf-8")
        start = source.index("async def _source_pixel_build_composite_candidates")
        end = source.index("async def _run_v149_generation")
        block = source[start:end]
        self.assertIn('_pixel_delta(celebrity_variant["output"], raw, user_placement)', block)
        self.assertIn('_pixel_delta(bytes(plate_output), raw, celebrity_placement)', block)
        self.assertIn('_human_cutout_problem(cutout, "user")', block)

    def test_placeholder_background_is_disabled(self):
        source = Path("celebrity_selfie_v149.py").read_text(encoding="utf-8")
        self.assertIn('"gemini,flux"', source)
        self.assertIn('os.environ["CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK"] = "0"', source)

    def test_sitecustomize_loads_v149_last(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v149 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v149"), source.index("from celebrity_selfie_v148"))

    def test_version_contract_points_to_v149(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v149-visible-human-layer-proof-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v149 import install as install_v149", source)
        self.assertIn("release_overlay={'v149' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
