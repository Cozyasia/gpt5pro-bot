# -*- coding: utf-8 -*-
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

import celebrity_selfie_v130_runtime as _runtime  # prepares the historical v127 alias
import celebrity_selfie_v130 as v130


def image_bytes(size=(900, 1100), *, detail=True):
    image = Image.new("RGB", size, (135, 115, 105))
    draw = ImageDraw.Draw(image)
    if detail:
        for x in range(0, size[0], 20):
            draw.line((x, 0, size[0] - x // 2, size[1]), fill=(40 + x % 180, 80, 150), width=4)
        draw.ellipse((260, 180, 640, 650), fill=(205, 165, 135), outline=(25, 25, 25), width=8)
        draw.ellipse((350, 330, 390, 370), fill=(0, 0, 0))
        draw.ellipse((510, 330, 550, 370), fill=(0, 0, 0))
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class CelebritySelfieV130HistoricalTests(unittest.TestCase):
    def test_historical_version_and_catalog_contract(self):
        source = Path("celebrity_selfie_v130.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v130-celebrity-selfie-identity-lock-2026-07-19"', source)
        self.assertEqual(len(v130.RU_IDS), 20)
        self.assertEqual(len(v130.US_IDS), 10)
        self.assertEqual(len(v130.engine.CATALOG.get("celebrities", [])), 30)

    def test_catalog_sources_are_exactly_20_and_10(self):
        ru = [line for line in Path("celebrity_library/catalog_ru_v1.tsv").read_text(encoding="utf-8").splitlines() if line.strip()]
        us = [line for line in Path("celebrity_library/catalog_us_v1.tsv").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(ru), 20)
        self.assertEqual(len(us), 10)
        self.assertTrue(any(line.startswith("ru_roman_abramovich\t") for line in ru))
        self.assertTrue(any(line.startswith("us_keanu_reeves\t") for line in us))

    def test_quality_metrics_accept_detailed_portrait_and_reject_small_image(self):
        metrics = v130._quality_metrics(image_bytes())
        self.assertEqual(v130._quality_problem(metrics), "")
        small = v130._quality_metrics(image_bytes((240, 240)))
        self.assertIn("малень", v130._quality_problem(small))

    def test_historical_v130_source_pair_contract_is_documented(self):
        source = Path("celebrity_selfie_v130.py").read_text(encoding="utf-8")
        self.assertIn('sheet = Image.new("RGB", (size * 2, size)', source)
        self.assertIn('"swap_faces_index": "0,1"', source)
        self.assertIn('"target_faces_index": "0,1"', source)

    def test_v130_runtime_is_historical_and_v135_is_registered(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("from celebrity_selfie_v130_runtime import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v131 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v132 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v133 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v134 import install_builder_hook", source)
        self.assertIn("from celebrity_selfie_v135 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v129 import install_builder_hook", source)


if __name__ == "__main__":
    unittest.main()
