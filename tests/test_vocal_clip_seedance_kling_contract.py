"""Regression contracts for the production singing-clip provider chain."""
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")


class VocalClipSeedanceKlingContractTests(unittest.TestCase):
    def test_seedance_uses_image_reference_and_persistent_task_id(self):
        start = SOURCE.index("async def _start_vocal_clip")
        end = SOURCE.index("async def _run_kling_text_shorts", start)
        flow = SOURCE[start:end]
        self.assertIn("seedance_generate(", flow)
        self.assertIn("reference_bytes=continuation_bytes", flow)
        self.assertIn("existing_task_id=existing_seedance_task", flow)
        self.assertIn('f"scene_{i}_seedance_task_id"', flow)
        self.assertNotIn("audio_urls", flow)

    def test_real_audio_lipsync_and_original_track_mux_remain_required(self):
        start = SOURCE.index("async def _start_vocal_clip")
        end = SOURCE.index("async def _run_kling_text_shorts", start)
        flow = SOURCE[start:end]
        self.assertIn("_apply_kling_lipsync_to_scene_file(", flow)
        self.assertIn("genuine audio-driven", flow)
        self.assertIn("_mux_video_audio_files_sync", flow)
        self.assertIn("несинхронизированный клип не отправляю", flow)

    def test_final_mux_never_loops_the_source_audio(self):
        start = SOURCE.index("def _mux_video_audio_files_sync")
        end = SOURCE.index("def _concat_video_segment_files_sync", start)
        mux = SOURCE[start:end]
        self.assertIn("source track must never be looped", mux)
        self.assertNotIn('"-stream_loop", "-1", "-i", audio_path', mux)


if __name__ == "__main__":
    unittest.main()
