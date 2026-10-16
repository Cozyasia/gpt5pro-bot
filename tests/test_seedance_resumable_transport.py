"""Offline contract tests for safe Seedance task submission and recovery."""
import asyncio
import unittest

import video_studio


FAKE_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 1024


class FakeResponse:
    def __init__(self, payload=None, *, content=b"", status=200):
        self.payload = payload
        self.content = content
        self.status_code = status
        self.text = content.decode("utf-8", "replace")

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    instances = []
    create_status = 200

    def __init__(self, **_kwargs):
        self.posts = []
        self.gets = []
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if self.create_status >= 400:
            return FakeResponse(content=b"provider error", status=self.create_status)
        return FakeResponse({"id": "seedance-task-1"})

    async def get(self, url, **_kwargs):
        self.gets.append(url)
        if url.endswith("/seedance-task-1"):
            return FakeResponse({"status": "completed", "video_url": "https://media.test/out.mp4"})
        if url == "https://media.test/out.mp4":
            return FakeResponse(content=FAKE_MP4)
        return FakeResponse(content=b"not found", status=404)


class SeedanceResumableTransportTests(unittest.TestCase):
    def setUp(self):
        self.original_client = video_studio.httpx.AsyncClient
        video_studio.httpx.AsyncClient = FakeClient
        FakeClient.instances.clear()
        FakeClient.create_status = 200

    def tearDown(self):
        video_studio.httpx.AsyncClient = self.original_client

    def test_records_task_id_before_polling(self):
        task_ids = []
        result = asyncio.run(video_studio.seedance_generate(
            api_key="test-key", base_url="https://api.test", prompt="vertical singer", seconds=10,
            on_task_id=task_ids.append, poll_interval_s=0,
        ))
        self.assertEqual(FAKE_MP4, result)
        self.assertEqual(["seedance-task-1"], task_ids)
        self.assertEqual(1, len(FakeClient.instances[0].posts))

    def test_existing_task_resumes_without_another_billable_post(self):
        result = asyncio.run(video_studio.seedance_generate(
            api_key="test-key", base_url="https://api.test", prompt="vertical singer", seconds=10,
            existing_task_id="seedance-task-1", poll_interval_s=0,
        ))
        self.assertEqual(FAKE_MP4, result)
        self.assertEqual([], FakeClient.instances[0].posts)

    def test_server_error_is_not_retried_with_a_fallback_model(self):
        FakeClient.create_status = 503
        with self.assertRaisesRegex(video_studio.SeedanceError, "503"):
            asyncio.run(video_studio.seedance_generate(
                api_key="test-key", base_url="https://api.test", prompt="vertical singer", seconds=10,
                model_fallbacks=["seedance-alias"], poll_interval_s=0,
            ))
        self.assertEqual(1, len(FakeClient.instances[0].posts))


if __name__ == "__main__":
    unittest.main()
