"""Offline contract tests for the 24-second, three-scene voice workflow.

No provider calls or paid generation.
"""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from neyrobot_prod.veo_multiscene import plan_video, estimated_provider_cost_usd
from neyrobot_prod.veo_tts_timeline import split_tts_master, mux_master_voice


class Veo24SecondTests(unittest.TestCase):
    def test_three_scenes_exactly(self):
        scenes = plan_video(24, "Раз два три четыре пять шесть")
        self.assertEqual(len(scenes), 3)
        self.assertEqual([(s.timeline_start, s.timeline_end) for s in scenes],
                         [(0, 8), (8, 16), (16, 24)])
        self.assertEqual(sum(s.generated_seconds for s in scenes), 24)

    def test_billed_generated_seconds(self):
        self.assertEqual(estimated_provider_cost_usd(24, 0.1), 2.4)
        self.assertEqual(estimated_provider_cost_usd(30, 0.1), 3.2)

    def test_voice_module_parses(self):
        path = Path(__file__).resolve().parents[1] / "neyrobot_prod/veo_tts_timeline.py"
        ast.parse(path.read_text(encoding="utf-8"))

    def test_rejects_other_duration_without_ffmpeg(self):
        with self.assertRaises(ValueError):
            split_tts_master("/not/there.wav", "/tmp/veo-not-created", seconds=30)

    def test_missing_master_fails_without_ffmpeg(self):
        with self.assertRaises(FileNotFoundError):
            split_tts_master("/not/there.wav", "/tmp/veo-not-created")

    def test_missing_mux_inputs_fails_without_ffmpeg(self):
        with self.assertRaises(FileNotFoundError):
            mux_master_voice("/not/there.mp4", "/not/there.wav", "/tmp/veo-not-created.mp4")

    def test_three_slices_use_same_source(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "master.wav"
            source.write_bytes(b"offline-test")
            with patch("neyrobot_prod.veo_tts_timeline.require_24_second_voice", return_value=24.0):
                with patch("neyrobot_prod.veo_tts_timeline.subprocess.run") as run:
                    paths = split_tts_master(source, Path(d) / "slices")
            self.assertEqual(len(paths), 3)
            self.assertEqual(run.call_count, 3)
            self.assertEqual([c.args[0][c.args[0].index("-ss") + 1] for c in run.call_args_list],
                             ["0", "8", "16"])
            self.assertTrue(all(str(source.resolve()) in c.args[0] for c in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
