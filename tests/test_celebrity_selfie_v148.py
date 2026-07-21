# -*- coding: utf-8 -*-
import json
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

import celebrity_selfie_v148 as v148


def _jpeg(width=1024, height=1280):
    image = Image.new("RGB", (width, height), (45, 55, 70))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = 35 + int(120 * y / max(1, height - 1))
        draw.line((0, y, width, y), fill=(shade, min(220, shade + 20), min(235, shade + 35)))
    out = BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


def _placement(x, y, w, h):
    return {
        "position": [x, y],
        "size": [w, h],
        "alpha_metrics": {
            "bbox": [10, 5, 490, 895],
            "transparent": 0.42,
            "border_opaque": 0.08,
            "transparent_corners": 4,
        },
    }


class CelebritySelfieV148Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v148.VERSION, "v148-schema-safe-layer-qc-2026-07-21")

    def test_gemini_payloads_never_send_rejected_image_config(self):
        variants = v148._gemini_payload_variants_no_aspect("empty restaurant")
        self.assertGreaterEqual(len(variants), 3)
        for name, payload in variants:
            serialized = json.dumps(payload, sort_keys=True).casefold()
            self.assertNotIn("responseformat", serialized, name)
            self.assertNotIn("response_format", serialized, name)
            self.assertNotIn("aspectratio", serialized, name)
            self.assertNotIn("aspect_ratio", serialized, name)
            self.assertNotIn("imagesize", serialized, name)
            self.assertNotIn("image_size", serialized, name)

    def test_source_layer_gate_accepts_profile_safe_metadata(self):
        raw = _jpeg()
        left = _placement(20, 210, 510, 940)
        right = _placement(510, 220, 500, 930)
        self.assertEqual(v148._source_layer_problem(raw, left, side="left", role="user"), "")
        self.assertEqual(v148._source_layer_problem(raw, right, side="right", role="celebrity"), "")
        self.assertEqual(v148._dual_layer_problem(raw, left, right), "")

    def test_source_layer_gate_rejects_wrong_side(self):
        raw = _jpeg()
        wrong = _placement(610, 200, 380, 900)
        problem = v148._source_layer_problem(raw, wrong, side="left", role="user")
        self.assertIn("not on the left", problem)

    def test_build_route_does_not_call_generic_final_face_detector(self):
        source = Path("celebrity_selfie_v148.py").read_text(encoding="utf-8")
        start = source.index("async def _source_pixel_build_composite_candidates")
        end = source.index("async def _run_v148_generation")
        block = source[start:end]
        self.assertNotIn("_final_layout_problem", block)
        self.assertNotIn("_main_faces", block)
        self.assertIn("_dual_layer_problem", block)
        self.assertIn("generic_face_detector_gate_used", block)

    def test_sitecustomize_loads_v148_last(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v148 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v148"), source.index("from celebrity_selfie_v147"))

    def test_version_contract_points_to_v148(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v148-schema-safe-layer-qc-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v148 import install as install_v148", source)
        self.assertIn("release_overlay={'v148' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
