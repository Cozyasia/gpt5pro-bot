import subprocess
import tempfile
import unittest
import ast
from pathlib import Path

from property_video_pipeline import (
    assemble_property_video,
    plan_property_scenes,
    resolve_reference_aspect,
    inspect_property_video,
    scene_prompt,
)
from property_video_execution import quote_for_job


class PropertyVideoPipelineTests(unittest.TestCase):
    def test_kling_builds_an_overlapping_route_instead_of_disjoint_pairs(self):
        scenes = plan_property_scenes(9, 20, "kling", "full")
        self.assertEqual(len(scenes), 4)
        self.assertEqual(
            [(scene.photo_index, scene.next_photo_index) for scene in scenes],
            [(0, 2), (2, 4), (4, 6), (6, 8)],
        )
        self.assertTrue(all(scene.next_photo_index is not None for scene in scenes))
        for current, following in zip(scenes, scenes[1:]):
            self.assertEqual(current.next_photo_index, following.photo_index)

    def test_all_three_engines_have_duration_bounded_multiscene_plans(self):
        for engine in ("kling", "veo", "seedance"):
            scenes = plan_property_scenes(30, 60, engine, "full")
            self.assertGreater(len(scenes), 1)
            self.assertTrue(all(scene.seconds >= 4 for scene in scenes))
            self.assertLessEqual(len(scenes), 12)

    def test_seedance_uses_selected_route_keyframes_without_fake_pairing(self):
        scenes = plan_property_scenes(9, 20, "seedance", "interior")
        self.assertEqual([scene.photo_index for scene in scenes], [0, 3, 5, 8])
        self.assertTrue(all(scene.next_photo_index is None for scene in scenes))

    def test_full_review_starts_with_establishing_view_and_preserves_order(self):
        scenes = plan_property_scenes(5, 30, "seedance", "full")
        self.assertEqual(scenes[0].role, "property establishing view")
        self.assertEqual([scene.photo_index for scene in scenes], [0, 1, 2, 3, 4])
        prompt = scene_prompt("Use the photos", scenes[1], len(scenes))
        self.assertIn("supplied reference photograph", prompt)
        self.assertIn("Do not invent", prompt)

    def test_short_review_selects_keyframes_and_preserves_route_overlap(self):
        scenes = plan_property_scenes(10, 20, "kling", "interior")
        self.assertEqual(len(scenes), 4)
        self.assertAlmostEqual(sum(scene.output_seconds for scene in scenes), 20)
        self.assertEqual(scenes[0].photo_index, 0)
        self.assertEqual(scenes[-1].next_photo_index, 9)
        for current, following in zip(scenes, scenes[1:]):
            self.assertEqual(current.next_photo_index, following.photo_index)

    def test_director_accepts_thirty_photos_and_long_tours(self):
        scenes = plan_property_scenes(30, 60, "kling", "full")
        self.assertEqual(len(scenes), 12)
        self.assertEqual(scenes[0].photo_index, 0)
        self.assertEqual(scenes[-1].next_photo_index, 29)

    def test_interior_prompt_does_not_bias_to_exterior_amenities(self):
        scene = plan_property_scenes(1, 8, "kling", "interior")[0]
        prompt = scene_prompt("interior tour", scene, 1)
        self.assertIn("visible interior room view", prompt)
        self.assertIn("Do not add exterior views", prompt)

    def test_scene_prompt_requires_a_real_transition_when_next_reference_exists(self):
        scenes = plan_property_scenes(3, 30, "kling", "full")
        prompt = scene_prompt("property walkthrough", scenes[0], len(scenes))
        self.assertIn("next reference photo", prompt)
        self.assertIn("continuous walkthrough", prompt)

    def test_scene_prompt_requires_first_person_translation_not_a_photo_pan(self):
        scene = plan_property_scenes(4, 10, "kling", "interior")[0]
        prompt = scene_prompt("property walkthrough", scene, 2).lower()
        self.assertIn("first-person", prompt)
        self.assertIn("camera position physically", prompt)
        self.assertIn("foreground parallax", prompt)
        self.assertIn("doorframe", prompt)
        self.assertIn("no digital zoom", prompt)
        self.assertIn("approximately 1.6 metres", prompt)
        self.assertIn("20-24mm", prompt)
        self.assertIn("shorter accurate shot", prompt)

    def test_unknown_room_connection_requests_a_cinematic_cut(self):
        scenes = plan_property_scenes(
            3, 10, "kling", "full",
            labels=["exterior", "bedroom", "kitchen"],
        )
        self.assertEqual(scenes[0].transition_kind, "cinematic_cut")
        prompt = scene_prompt("property walkthrough", scenes[0], len(scenes)).lower()
        self.assertIn("natural cinematic cut", prompt)
        self.assertIn("do not invent a corridor", prompt)

    def test_director_prefers_room_boundaries_over_duplicate_views(self):
        scenes = plan_property_scenes(
            6, 10, "kling", "interior",
            labels=["living_room", "living_room", "living_room", "living_room", "kitchen", "bedroom"],
        )
        self.assertEqual(
            [(scene.photo_index, scene.next_photo_index) for scene in scenes],
            [(0, 4), (4, 5)],
        )

    def test_kling_property_wrapper_does_not_forbid_the_requested_transition(self):
        source = Path("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(
            item for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == "_property_video_prompt"
        )
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
        prompt = namespace["_property_video_prompt"]("walk into the next supplied view", 5).lower()
        self.assertNotIn("do not redesign, redecorate, extend or connect spaces", prompt)
        self.assertIn("camera position physically", prompt)
        self.assertIn("no digital zoom", prompt)

    def test_quote_is_scene_aware(self):
        one = quote_for_job("seedance", 1, 10, "interior")
        many = quote_for_job("seedance", 5, 30, "full")
        self.assertGreater(many["scene_count"], one["scene_count"])
        self.assertGreater(many["provider_cost_usd"], one["provider_cost_usd"])
        self.assertGreater(many["retail_usd"], 0)

    def test_ffmpeg_assembly_retimes_scene_to_preserve_terminal_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "transition.mp4"
            output = root / "final.mp4"
            subprocess.run([
                "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
                "color=c=red:s=160x90:d=4.5", "-f", "lavfi", "-i",
                "color=c=blue:s=160x90:d=0.5", "-filter_complex",
                "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]",
                "-map", "[v]", "-r", "30", "-c:v", "libx264", str(source),
            ], check=True, capture_output=True)
            assemble_property_video([str(source)], str(output), 4, scene_durations=[4])
            pixel = subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-ss", "3.9", "-i", str(output),
                "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "pipe:1",
            ], check=True, capture_output=True).stdout
            self.assertGreater(pixel[2], pixel[0], "terminal reference frame was trimmed away")

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

    def test_auto_aspect_uses_the_majority_of_reference_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from PIL import Image
            paths = []
            for index, size in enumerate(((1200, 800), (900, 600), (600, 900))):
                path = root / f"{index}.jpg"
                Image.new("RGB", size, "white").save(path)
                paths.append(str(path))
            self.assertEqual(resolve_reference_aspect(paths, "auto"), "16:9")
            self.assertEqual(resolve_reference_aspect(paths, "9:16"), "9:16")

    def test_horizontal_assembly_fills_the_frame_without_black_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            output = root / "final.mp4"
            subprocess.run([
                "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
                "color=c=red:s=320x240:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(source),
            ], check=True, capture_output=True)
            assemble_property_video([str(source)], str(output), 1, aspect_ratio="16:9")
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(output),
            ], check=True, capture_output=True, text=True)
            self.assertEqual(probe.stdout.strip(), "1280x720")
            edge = subprocess.run([
                "ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(output),
                "-frames:v", "1", "-vf", "crop=2:2:0:0", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "pipe:1",
            ], check=True, capture_output=True).stdout
            self.assertGreater(edge[0], 100, "the output still has a black padded border")
            report = inspect_property_video(str(output), 1, "16:9")
            self.assertEqual((report["width"], report["height"]), (1280, 720))
            self.assertEqual(report["black_border_samples"], 0)


if __name__ == "__main__":
    unittest.main()
