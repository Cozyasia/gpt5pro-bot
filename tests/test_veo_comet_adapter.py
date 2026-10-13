import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from neyrobot_prod.veo_comet_adapter import submit_veo_task, UncertainVeoSubmission


class VeoAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_submission(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"task_id": "task-1"}}
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        with patch("neyrobot_prod.veo_comet_adapter.httpx.AsyncClient", return_value=client):
            task = await submit_veo_task("https://example.invalid", "key", "veo3.1-fast", "Russian speech")
        self.assertEqual(task, "task-1")
        client.post.assert_awaited_once()
        args = client.post.await_args.kwargs
        self.assertEqual(args["files"][0], ("model", (None, "veo3.1-fast")))
        self.assertEqual(args["files"][2], ("size", (None, "9:16")))

    async def test_missing_task_id_is_uncertain(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"status": "queued"}
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        with patch("neyrobot_prod.veo_comet_adapter.httpx.AsyncClient", return_value=client):
            with self.assertRaises(UncertainVeoSubmission):
                await submit_veo_task("https://example.invalid", "key", "veo3.1-fast", "Prompt")
        client.post.assert_awaited_once()
