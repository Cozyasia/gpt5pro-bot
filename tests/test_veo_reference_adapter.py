"""Offline validation for optional CometAPI presenter reference."""
import ast
import tempfile
import unittest
from pathlib import Path

from neyrobot_prod.veo_comet_adapter import submit_veo_task


class ReferenceContractTests(unittest.TestCase):
    def test_adapter_parses(self):
        ast.parse(Path("neyrobot_prod/veo_comet_adapter.py").read_text(encoding="utf-8"))

    def test_missing_image_rejected_before_network(self):
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(submit_veo_task("https://example.invalid", "dummy", "veo3.1-fast", "test", reference_image="/nonexistent/presenter.jpg"))

    def test_wrong_extension_rejected_before_network(self):
        import asyncio
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "unsafe.txt"
            p.write_text("not an image")
            with self.assertRaises(ValueError):
                asyncio.run(submit_veo_task("https://example.invalid", "dummy", "veo3.1-fast", "test", reference_image=str(p)))


if __name__ == "__main__":
    unittest.main()
