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
        return FakeResponse({"data": {"task_id": "lip-1"}})

    async def get(self, url, **_kwargs):
        self.gets.append(url)
        if url == "https://media.test/lipsynced.mp4":
            return FakeResponse(content=self.media, content_type="video/mp4")
        if url.endswith("/lip-1"):
            return FakeResponse({"data": {"task_status": "succeed", "task_result": {
                "videos": [{"url": "https://media.test/lipsynced.mp4"}]
            }}})
        return FakeResponse(status=404)


def load_transport():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {
        "_run_kling_lipsync_result_bytes", "_create_and_poll_i2v_bytes",
        "_poll_video_task_for_bytes", "_download_binary_from_url", "_extract_first_url",
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
        "KLING_LIPSYNC_CREATE_PATH": "/kling/v1/videos/lip-sync",
        "KLING_LIPSYNC_STATUS_PATH": "/kling/v1/videos/lip-sync/{id}",
        "VOCAL_CLIP_KLING_MAX_WAIT_S": 30, "VIDEO_POLL_DELAY_S": 0,
        "_api_error_preview": lambda response: response.text[:100],
        "log": SimpleNamespace(warning=lambda *_a: None, info=lambda *_a: None),
        "json": __import__("json"), "time": __import__("time"),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


class KlingLipSyncTransportTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        FakeClient.media = FAKE_MP4

    def test_uses_official_audio2video_url_payload_and_returns_mp4(self):
        env = load_transport()
        result = asyncio.run(env["_run_kling_lipsync_result_bytes"](
            "https://media.test/video.mp4", "https://media.test/audio.mp3", max_wait_s=30,
        ))

        self.assertEqual(FAKE_MP4, result)
        client, = FakeClient.instances
        self.assertEqual("https://api.test/kling/v1/videos/lip-sync", client.posts[0][0])
        self.assertEqual({
            "input": {
                "video_url": "https://media.test/video.mp4",
                "mode": "audio2video",
                "audio_type": "url",
                "audio_url": "https://media.test/audio.mp3",
            }
        }, client.posts[0][1])

    def test_rejects_non_mp4_result_instead_of_falling_back_unsynced(self):
        FakeClient.media = b'{"error":"not video"}' + b" " * 1024
        env = load_transport()
        with self.assertRaisesRegex(RuntimeError, "not an MP4"):
            asyncio.run(env["_run_kling_lipsync_result_bytes"](
                "https://media.test/video.mp4", "https://media.test/audio.mp3", max_wait_s=30,
            ))


if __name__ == "__main__":
    unittest.main()
