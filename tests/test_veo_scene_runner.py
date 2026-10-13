import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from neyrobot_prod.veo_task_journal import read_job, mark_scene
from neyrobot_prod.veo_scene_runner import run_journaled_scene, ReconciliationRequired


class SceneRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_once_and_persist(self):
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "job.json"
            submit = AsyncMock(return_value="provider-1")
            poll = AsyncMock(return_value=b"video")
            save = AsyncMock()
            result = await run_journaled_scene(journal, 1, submit, poll, save)
            self.assertEqual(result, b"video")
            self.assertEqual(read_job(journal)["scenes"]["1"]["state"], "completed")
            submit.assert_awaited_once()
            save.assert_awaited_once()

    async def test_resume_accepted_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "job.json"
            mark_scene(journal, 1, "accepted", "provider-1")
            submit = AsyncMock()
            await run_journaled_scene(
                journal, 1, submit, AsyncMock(return_value=b"video"), AsyncMock())
            submit.assert_not_awaited()

    async def test_ambiguous_submission_blocks_retry(self):
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "job.json"
            submit = AsyncMock(side_effect=TimeoutError("unknown"))
            with self.assertRaises(TimeoutError):
                await run_journaled_scene(
                    journal, 1, submit, AsyncMock(), AsyncMock())
            self.assertEqual(read_job(journal)["scenes"]["1"]["state"], "uncertain")
            with self.assertRaises(ReconciliationRequired):
                await run_journaled_scene(
                    journal, 1, submit, AsyncMock(), AsyncMock())
            submit.assert_awaited_once()

    async def test_completed_scene_never_resubmitted(self):
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "job.json"
            mark_scene(journal, 1, "completed", "provider-1")
            submit = AsyncMock()
            with self.assertRaises(ReconciliationRequired):
                await run_journaled_scene(
                    journal, 1, submit, AsyncMock(), AsyncMock())
            submit.assert_not_awaited()
