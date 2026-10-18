"""Regression tests for Seedance captions and vertical safe-area wrapping."""
import re
import unittest
from pathlib import Path
from neyrobot_prod.ad_video_safe_delivery import _wrap_caption


class StudioCaptionsTests(unittest.TestCase):
    def test_wrap_long_cyrillic_caption(self):
        title = "КРАСОТА В КАЖДОЙ КАПЛЕ"
        lines = _wrap_caption(title).splitlines()
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 18 for line in lines))
        self.assertEqual(" ".join(lines), title)

    def test_studio_strips_timeline_from_provider_prompt(self):
        source = Path("main.py").read_text(encoding="utf-8")
        studio = source.split("async def _start_video_studio(", 1)[1].split("async def _start_text_video(", 1)[0]
        self.assertIn('visual_prompt = re.sub(', studio)
        self.assertIn('scene_prompt = seedance_scene_prompt(scene, visual_prompt)', studio)
        self.assertIn('NO text or typography', studio)

    def test_overlay_uses_wrapped_textfiles(self):
        source = Path("neyrobot_prod/ad_video_safe_delivery.py").read_text(encoding="utf-8")
        self.assertIn('caption_file.write_text(_wrap_caption(caption)', source)
        self.assertIn("fontsize=h/34", source)
        self.assertIn("x=(w-text_w)/2", source)


if __name__ == "__main__":
    unittest.main()
