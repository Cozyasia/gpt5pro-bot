import subprocess
import tempfile
import unittest
from pathlib import Path

from property_video_pipeline import assemble_property_video, plan_property_scenes, scene_prompt
from property_video_execution import quote_for_job


class PropertyVideoPipelineTests(unittest.TestCase):
    def test_photo_counts_are_supported_without_using_only_first_photo(self):
        for count in (1, 5, 9, 10):
            scenes = plan_property_scenes(count, 30, "kling", "full")
            self.assertGreaterEqual(len(scenes), 1)
            self.assertGreaterEqual(len(scenes), count)
            self.assertEqual(set(range(count)), {scene.photo_index for scene in scenes})

    def test_all_three_engines_have_multiscene_plans(self):
        for engine in ("kling", "veo", "seedance"):
            scenes = plan_property_scenes(5, 30, engine, "full")
            self.assertGreater(len(scenes), 1)
            self.assertTrue(all(scene.seconds >= 4 for scene in scenes))
            self.assertEqual(set(range(5)), {scene.photo_index for scene in scenes})

    def test_full_review_starts_with_establishing_view_and_preserves_order(self):
        scenes = plan_property_scenes(5, 30, "seedance", "full")
        self.assertEqual(scenes[0].role, "property establishing view")
        self.assertEqual([scene.photo_index for scene in scenes], list(range(len(scenes))))
        prompt = scene_prompt("Use the photos", scenes[1], len(scenes))
        self.assertIn("supplied reference photograph", prompt)
        self.assertIn("Do not invent", prompt)

    def test_short_review_trims_every_reference_slot(self):
        scenes = plan_property_scenes(10, 20, "kling", "interior")
        self.assertEqual(len(scenes), 10)
        self.assertAlmostEqual(sum(scene.output_seconds for scene in scenes), 20)
        self.assertEqual([scene.photo_index for scene in scenes], list(range(10)))

    def test_interior_prompt_does_not_bias_to_exterior_amenities(self):
        scene = plan_property_scenes(1, 8, "kling", "interior")[0]
        prompt = scene_prompt("interior tour", scene, 1)
        self.assertIn("visible interior room view", prompt)
        self.assertIn("Do not add exterior views", prompt)

    def test_quote_is_scene_aware(self):
        one = quote_for_job("seedance", 1, 10, "interior")
        many = quote_for_job("seedance", 5, 30, "full")
        self.assertGreater(many["scene_count"], one["scene_count"])
        self.assertGreater(many["provider_cost_usd"], one["provider_cost_usd"])
        self.assertGreater(many["retail_usd"], 0)

    def test_ffmpeg_assembly_normalizes_and_trims_final_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clips = []
            for index in range(2):
                clip = root / f"clip_{index}.mp4"
                subprocess.run([
                    "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
                    f"color=c={'blue' if index else 'red'}:s=320x240:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(clip),
                ], check=True, capture_output=True)
                clips.append(str(clip))
            output = root / "final.mp4"
            assemble_property_video(clips, str(output), 1)
            self.assertTrue(output.is_file())
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(output),
            ], check=True, capture_output=True, text=True)
            self.assertLessEqual(float(probe.stdout.strip()), 1.2)


if __name__ == "__main__":
    unittest.main()
