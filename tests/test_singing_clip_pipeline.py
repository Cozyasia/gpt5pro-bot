"""No paid provider calls: local validation tests for singing-clip planning."""
import unittest
from neyrobot_prod.singing_clip_pipeline import SingingClipJob, segment_ranges, seedance_reference_prompt
from neyrobot_prod.singing_clip_assembly import assemble_singing_clip

class SingingClipTests(unittest.TestCase):
    def test_requires_identity_and_audio(self):
        job = SingingClipJob(user_id=1, prompt="Russian pop song")
        self.assertFalse(job.ready_for_video())
        ready = SingingClipJob(user_id=1, prompt="Russian pop song",
                               suno_audio_url="https://example.com/song.mp3",
                               reference_image_url="https://example.com/portrait.jpg")
        self.assertTrue(ready.ready_for_video())

    def test_segment_boundaries(self):
        self.assertEqual(segment_ranges(31, 15), [(0.0, 15), (15, 30), (30, 31)])
        with self.assertRaises(ValueError):
            segment_ranges(0)

    def test_prompt_preserves_original_audio(self):
        self.assertIn("original Suno audio", seedance_reference_prompt())

    def test_assembly_rejects_missing_inputs(self):
        with self.assertRaises(FileNotFoundError):
            assemble_singing_clip(["/missing/clip.mp4"], "/missing/audio.mp3", "/tmp/clip.mp4")

if __name__ == "__main__":
    unittest.main()
