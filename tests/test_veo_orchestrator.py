import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from neyrobot_prod.veo_orchestrator import render_multiscene_video, SceneGenerationError

class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_generation_and_single_assembly(self):
        calls = []
        async def generator(prompt, index, total):
            calls.append((index, total, prompt))
            return b"x" * 2048
        with TemporaryDirectory() as td:
            destination = Path(td) / "out.mp4"
            with patch("neyrobot_prod.veo_orchestrator.assemble_vertical_video", return_value=destination) as assembly:
                result = await render_multiscene_video(
                    duration_seconds=30, spoken_script="Привет это тест",
                    visual_brief="A person in a studio", generate_scene=generator,
                    output_path=destination)
            self.assertEqual(result, destination)
            self.assertEqual(len(calls), 4)
            self.assertEqual([c[0] for c in calls], [1, 2, 3, 4])
            assembly.assert_called_once()

    async def test_stop_on_failure_without_retries(self):
        calls = []
        async def generator(prompt, index, total):
            calls.append(index)
            if index == 2:
                raise RuntimeError("provider error")
            return b"x" * 2048
        with TemporaryDirectory() as td:
            with self.assertRaises(SceneGenerationError):
                await render_multiscene_video(
                    duration_seconds=60, spoken_script="Тест",
                    visual_brief="Studio", generate_scene=generator,
                    output_path=Path(td) / "out.mp4")
        self.assertEqual(calls, [1, 2])

if __name__ == "__main__":
    unittest.main()
