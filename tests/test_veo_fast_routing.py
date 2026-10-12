"""Static regression guards for Veo integration; no provider requests or charges."""
from pathlib import Path
import ast
import unittest

SOURCE = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")

class VeoRoutingTests(unittest.TestCase):
    def test_main_syntax(self):
        ast.parse(SOURCE)

    def test_menu_routes(self):
        for token in ('tv_engine_veo', '"veo", prefix="act"', '"veo", prefix="fun"'):
            self.assertIn(token, SOURCE)

    def test_comet_request(self):
        for token in ('"veo3.1-fast"', '"/v1/videos"', '"__multipart"', '"size": "9:16"'):
            self.assertIn(token, SOURCE)

    def test_no_automatic_paid_fallback(self):
        start = SOURCE.index('    if engine == "veo":\n        veo_prompt')
        end = SOURCE.index('    if engine == "sora":', start)
        block = SOURCE[start:end]
        self.assertEqual(block.count('("/v1/videos", payload)'), 1)
        self.assertIn('max_wait_s=1200', block)

if __name__ == "__main__":
    unittest.main()
