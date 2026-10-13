import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neyrobot_prod.veo_resumable_pipeline import resume_veo_job
from neyrobot_prod.veo_scene_artifacts import save_scene
from neyrobot_prod.veo_task_journal import mark_scene


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_24_second_pipeline_can_stop_after_persisting_veo_scenes(self):
        """Lip-sync must run before the final assembly, not after native Veo audio."""
        with tempfile.TemporaryDirectory() as td:
            submitted = []

            async def submit(prompt, index):
                submitted.append(index)
                return "id" + str(index)

            async def poll(_task_id):
                return b"x" * 2048

            with patch("neyrobot_prod.veo_resumable_pipeline.assemble_vertical_video") as assemble:
                clips = await resume_veo_job(
                    job_directory=td, duration_seconds=24,
                    spoken_script="Один два три четыре пять шесть",
                    visual_brief="Studio", submit=submit, poll=poll,
                    assemble=False,
                )
            self.assertEqual(submitted, [1, 2, 3])
            self.assertEqual([p.name for p in clips], ["scene_01.mp4", "scene_02.mp4", "scene_03.mp4"])
            assemble.assert_not_called()

    async def test_resume_completed_scene_and_poll_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "journal.json"
            mark_scene(journal, 1, "completed", "id1")
            save_scene(td, 1, b"x" * 2048)
            mark_scene(journal, 2, "accepted", "id2")
            submitted, polled = [], []
            async def submit(prompt, index):
                submitted.append(index)
                return "id" + str(index)
            async def poll(task_id):
                polled.append(task_id)
                return b"x" * 2048
            output = Path(td) / "final.mp4"
            with patch("neyrobot_prod.veo_resumable_pipeline.assemble_vertical_video", return_value=output) as assemble:
                result = await resume_veo_job(
                    job_directory=td, duration_seconds=15,
                    spoken_script="Привет это короткий тест",
                    visual_brief="Studio", submit=submit, poll=poll)
            self.assertEqual(result, output)
            self.assertEqual(submitted, [])
            self.assertEqual(polled, ["id2"])
            assemble.assert_called_once()

    async def test_missing_completed_artifact_does_not_regenerate(self):
        with tempfile.TemporaryDirectory() as td:
            mark_scene(Path(td) / "journal.json", 1, "completed", "id1")
            async def submit(prompt, index):
                self.fail("Must not resubmit completed scene")
            async def poll(task_id):
                self.fail("Must not poll")
            with self.assertRaises(FileNotFoundError):
                await resume_veo_job(
                    job_directory=td, duration_seconds=8,
                    spoken_script="Тест", visual_brief="Studio",
                    submit=submit, poll=poll)
