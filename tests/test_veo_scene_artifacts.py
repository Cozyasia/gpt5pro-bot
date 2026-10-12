import tempfile
import unittest
from pathlib import Path
from neyrobot_prod.veo_scene_artifacts import (
    save_scene, load_scene, list_complete_scenes, scene_file
)


class SceneArtifactsTests(unittest.TestCase):
    def test_round_trip_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            a = b"a" * 2048
            b = b"b" * 2048
            save_scene(td, 2, b)
            save_scene(td, 1, a)
            self.assertEqual(load_scene(td, 1), a)
            self.assertEqual(list_complete_scenes(td, 2), [
                Path(td) / "scene_01.mp4", Path(td) / "scene_02.mp4"
            ])

    def test_missing_scene_blocks_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            save_scene(td, 1, b"a" * 2048)
            with self.assertRaises(FileNotFoundError):
                list_complete_scenes(td, 2)

    def test_rejects_empty_and_invalid_index(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                save_scene(td, 1, b"")
            with self.assertRaises(ValueError):
                scene_file(td, 0)

if __name__ == "__main__":
    unittest.main()
