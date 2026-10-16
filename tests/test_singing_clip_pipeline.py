"""No paid provider calls: local validation tests for singing-clip planning."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from neyrobot_prod.singing_clip_pipeline import SingingClipJob, segment_ranges, seedance_reference_prompt, require_audio_driven_lipsync
from neyrobot_prod.singing_clip_assembly import assemble_singing_clip

class SingingClipTests(unittest.TestCase):
    def test_requires_identity_and_audio(self):
        job = SingingClipJob(user_id=1, prompt="Russian pop song")
        self.assertFalse(job.ready_for_video())
        ready = SingingClipJob(user_id=1, prompt="Russian pop song",
                               suno_audio_url="https://example.com/song.mp3",
                               reference_image_url="https://example.com/portrait.jpg")
        self.assertTrue(ready.ready_for_video())

    def test_rejects_unsafe_or_missing_assets(self):
        for url in ("http://example.com/audio.mp3", "file:///tmp/audio.mp3", "https://u:p@example.com/audio.mp3"):
            job = SingingClipJob(user_id=1, prompt="song", suno_audio_url=url,
                                 reference_image_url="https://example.com/portrait.jpg")
            with self.assertRaises(ValueError):
                job.validated_inputs()
        with self.assertRaises(ValueError):
            SingingClipJob(user_id=1, prompt="song").validated_inputs()

    def test_unverified_lipsync_fails_closed(self):
        with self.assertRaises(RuntimeError):
            require_audio_driven_lipsync(supports_audio_reference=False, provider_name="Seedance")
        require_audio_driven_lipsync(supports_audio_reference=True, provider_name="VerifiedProvider")

    def test_segment_boundaries(self):
        self.assertEqual(segment_ranges(31, 15), [(0.0, 15), (15, 30), (30, 31)])
        with self.assertRaises(ValueError):
            segment_ranges(0)

    def test_prompt_preserves_original_audio(self):
        self.assertIn("original Suno audio", seedance_reference_prompt())

    def test_assembly_uses_original_audio_and_safe_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            segment = Path(folder) / "scene one.mp4"
            audio = Path(folder) / "suno original.mp3"
            output = Path(folder) / "result.mp4"
            segment.write_bytes(b"mock-video")
            audio.write_bytes(b"mock-audio")
            def fake_ffmpeg(args, **kwargs):
                self.assertEqual(args[0], "ffmpeg")
                self.assertIn(str(audio), args)
                self.assertIn("-filter_complex", args)
                self.assertIn("-map", args)
                self.assertIn("1:a:0", args)
                self.assertNotIn("shell", kwargs)
                output.write_bytes(b"mock-result")
            with patch("neyrobot_prod.singing_clip_assembly.subprocess.run", side_effect=fake_ffmpeg) as run:
                self.assertEqual(assemble_singing_clip([str(segment)], str(audio), str(output)), str(output))
                run.assert_called_once()

    def test_assembly_refuses_to_overwrite_original_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            segment = Path(folder) / "scene.mp4"
            audio = Path(folder) / "song.mp3"
            segment.write_bytes(b"mock-video")
            audio.write_bytes(b"mock-audio")
            with self.assertRaises(ValueError):
                assemble_singing_clip([str(segment)], str(audio), str(audio))

    def test_assembly_rejects_missing_inputs(self):
        with self.assertRaises(FileNotFoundError):
            assemble_singing_clip(["/missing/clip.mp4"], "/missing/audio.mp3", "/tmp/clip.mp4")

if __name__ == "__main__":
    unittest.main()
