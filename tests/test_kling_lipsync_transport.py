import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"
FAKE_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 1024


class FakeResponse:
    def __init__(self, payload=None, content=b"", content_type="application/json", status=200):
        self.payload = payload
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.text = content.decode("utf-8", "replace")

    def json(self):
        return self.payload


class FakeClient:
    instances = []
    media = FAKE_MP4
    create_status = 200
    create_events = []
    poll_payload = None

    def __init__(self, **_kwargs):
        self.posts = []
        self.gets = []
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, url, headers, json):
        self.posts.append((url, json))
        if url.endswith("identify-face"):
            return FakeResponse({"data": {"session_id": "session-1", "face_data": [{"face_id": "face-1"}]}})
        if self.create_events:
            event = self.create_events.pop(0)
            if isinstance(event, Exception):
                raise event
            if event != 200:
                return FakeResponse(content=b"temporary provider error", status=event)
        if self.create_status != 200:
            return FakeResponse(content=b"bad route", status=self.create_status)
        return FakeResponse({"data": {"task_id": "lip-1"}})

    async def get(self, url, **_kwargs):
        self.gets.append(url)
        if url == "https://media.test/lipsynced.mp4":
            return FakeResponse(content=self.media, content_type="video/mp4")
        if url.endswith("/lip-1"):
            if self.poll_payload is not None:
                return FakeResponse(self.poll_payload)
            return FakeResponse({"data": {"task_status": "succeed", "task_result": {
                "videos": [{"url": "https://media.test/lipsynced.mp4"}]
            }}})
        return FakeResponse(status=404)


def load_transport():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {
        "_run_kling_lipsync_result_bytes", "_kling_post_json_with_retry",
        "_poll_video_task_for_bytes", "_download_binary_from_url", "_extract_first_url",
        "_provider_data_object", "_provider_task_id",
    }
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]

    async def no_delay(_delay):
        pass

    env = {
        "httpx": SimpleNamespace(AsyncClient=FakeClient),
        "asyncio": SimpleNamespace(sleep=no_delay),
        "KLING_API_KEY": "test-key", "COMET_API_KEY": "",
        "COMET_BASE_URL": "https://api.test",
        "KLING_LIPSYNC_ENABLED": True,
        "KLING_IDENTIFY_FACE_PATH": "/kling/v1/videos/identify-face",
        "KLING_LIPSYNC_CREATE_PATH": "/kling/v1/videos/advanced-lip-sync",
        "KLING_LIPSYNC_STATUS_PATH": "/kling/v1/videos/lip-sync/{id}",
        "KLING_LIPSYNC_RETRY_ATTEMPTS": 3, "KLING_LIPSYNC_RETRY_BASE_S": 0,
        "VOCAL_CLIP_KLING_MAX_WAIT_S": 30, "VIDEO_POLL_DELAY_S": 0,
        "_api_error_preview": lambda response: response.text[:100],
        "log": SimpleNamespace(warning=lambda *_a: None, info=lambda *_a: None),
        "json": __import__("json"), "time": __import__("time"), "uuid": __import__("uuid"),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


class KlingLipSyncTransportTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        FakeClient.media = FAKE_MP4
        FakeClient.create_status = 200
        FakeClient.create_events = []
        FakeClient.poll_payload = None

    def test_uses_identify_then_advanced_lipsync_and_returns_mp4(self):
        env = load_transport()
        result = asyncio.run(env["_run_kling_lipsync_result_bytes"](
            "https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=6000, max_wait_s=30,
        ))

        self.assertEqual(FAKE_MP4, result)
        client, = FakeClient.instances
        self.assertTrue(client.posts[0][0].endswith("/identify-face"))
        self.assertTrue(client.posts[1][0].endswith("/advanced-lip-sync"))
        self.assertEqual("session-1", client.posts[1][1]["session_id"])
        self.assertEqual("face-1", client.posts[1][1]["face_choose"][0]["face_id"])
        self.assertEqual(6000, client.posts[1][1]["face_choose"][0]["sound_end_time"])

    def test_404_is_terminal_and_not_retried(self):
        FakeClient.create_status = 404
        env = load_transport()
        with self.assertRaisesRegex(RuntimeError, "unsupported endpoint"):
            asyncio.run(env["_run_kling_lipsync_result_bytes"]("https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=6000))
        self.assertEqual(2, len(FakeClient.instances[0].posts))

    def test_rejects_too_short_interval_before_provider(self):
        env = load_transport()
        with self.assertRaisesRegex(ValueError, "2000.*10000"):
            asyncio.run(env["_run_kling_lipsync_result_bytes"]("https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=1000))
        self.assertEqual([], FakeClient.instances)

    def test_rejects_non_mp4_result_instead_of_falling_back_unsynced(self):
        FakeClient.media = b'{"error":"not video"}' + b" " * 1024
        env = load_transport()
        with self.assertRaisesRegex(RuntimeError, "not an MP4"):
            asyncio.run(env["_run_kling_lipsync_result_bytes"](
                "https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=6000, max_wait_s=30,
            ))

    def test_retries_429_and_5xx_then_succeeds(self):
        FakeClient.create_events = [429, 503, 200]
        env = load_transport()
        result = asyncio.run(env["_run_kling_lipsync_result_bytes"](
            "https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=6000, max_wait_s=30,
        ))
        self.assertEqual(FAKE_MP4, result)
        self.assertEqual(4, len(FakeClient.instances[0].posts))

    def test_retries_transport_timeout_then_succeeds(self):
        FakeClient.create_events = [TimeoutError("provider timeout"), 200]
        env = load_transport()
        result = asyncio.run(env["_run_kling_lipsync_result_bytes"](
            "https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=6000, max_wait_s=30,
        ))
        self.assertEqual(FAKE_MP4, result)
        self.assertEqual(3, len(FakeClient.instances[0].posts))

    def test_terminal_provider_failure_is_not_treated_as_processing(self):
        FakeClient.poll_payload = {"data": {"task_status": "failed", "message": "invalid face"}}
        env = load_transport()
        with self.assertRaisesRegex(RuntimeError, "render failed"):
            asyncio.run(env["_run_kling_lipsync_result_bytes"](
                "https://media.test/video.mp4", "https://media.test/audio.mp3", duration_ms=6000, max_wait_s=30,
            ))


if __name__ == "__main__":
    unittest.main()
