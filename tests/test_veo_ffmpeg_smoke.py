"""Real FFmpeg smoke test for assembled native-audio scenes (no provider charges)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from neyrobot_prod.veo_assembler import assemble_vertical_video, probe_duration


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class AssemblySmokeTests(unittest.TestCase):
    def test_two_native_audio_clips_to_15_seconds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clips = []
            for i in range(2):
                clip = root / f"scene{i}.mp4"
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x568:r=24:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
                ], check=True, timeout=90)
                clips.append(clip)
            output = assemble_vertical_video(clips, root / "final.mp4", 15, width=320, height=568)
            self.assertTrue(output.is_file())
            self.assertAlmostEqual(probe_duration(output), 15, delta=0.15)


if __name__ == "__main__":
    unittest.main()
