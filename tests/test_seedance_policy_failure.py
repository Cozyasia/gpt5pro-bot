import unittest
from unittest.mock import AsyncMock, patch
import httpx
from video_studio import seedance_generate, SeedanceError

class SeedancePolicyFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_policy_failure_is_explained_without_retry(self):
        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.post = AsyncMock(return_value=httpx.Response(200, json={"id": "task-1"}, request=httpx.Request("POST", "https://example.test/v1/videos")))
                self.get = AsyncMock(return_value=httpx.Response(200, json={"status": "failed", "error": {"code": "OutputVideoSensitiveContentDetected.PolicyViolation", "message": "copyright restrictions"}}, request=httpx.Request("GET", "https://example.test/v1/videos/task-1")))
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
        client = FakeClient()
        with patch("video_studio.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(SeedanceError, "автоматический повтор отключён"):
                await seedance_generate(api_key="test", base_url="https://example.test", prompt="original cosmetic product", seconds=8, poll_interval_s=0.01)
        self.assertEqual(client.post.await_count, 1)

if __name__ == "__main__":
    unittest.main()
