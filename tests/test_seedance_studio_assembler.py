import ast
import re
import unittest
from pathlib import Path

from neyrobot_prod.seedance_assembler import assemble_seedance_video


class SeedanceStudioRegressionTests(unittest.TestCase):
    def test_reject_empty_inputs_before_ffmpeg(self):
        with self.assertRaisesRegex(ValueError, "Invalid Seedance"):
            assemble_seedance_video([], "/tmp/not-created.mp4", 8)

    def test_studio_does_not_use_veo_assembler(self):
        source = Path("main.py").read_text(encoding="utf-8")
        studio = source.split("async def _start_video_studio(", 1)[1].split("async def _start_text_video(", 1)[0]
        self.assertIn("from neyrobot_prod.seedance_assembler import assemble_seedance_video", studio)
        self.assertNotIn("from neyrobot_prod.veo_assembler", studio)
        self.assertIn("scene_seconds = ([duration] if len(plan.scenes) == 1", studio)
        self.assertIn("seconds = scene_seconds[position - 1]", studio)
        self.assertIn("assemble_seedance_video,", studio)
        self.assertIn("                duration,", studio)

    def test_caption_regex_matches_russian_timeline(self):
        source = Path("main.py").read_text(encoding="utf-8")
        studio = source.split("async def _start_video_studio(", 1)[1].split("async def _start_text_video(", 1)[0]
        ast.parse("async def _start_video_studio("+studio)
        pattern = r"(?im)^\s*ТИТРЫ\s*:\s*(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*\|\s*(.+?)\s*$"
        prompt = "ТИТРЫ: 0-3 | КРАСОТА В КАЖДОЙ КАПЛЕ\nТИТРЫ: 3-8 | ПОПРОБУЙТЕ СЕГОДНЯ"
        self.assertEqual(len(re.findall(pattern, prompt)), 2)


if __name__ == "__main__":
    unittest.main()
