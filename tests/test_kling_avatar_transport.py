import ast
import asyncio
import base64
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

    def __init__(self, **kwargs):
        self.posts = []
        self.gets = []
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def post(self, url, headers, json):
        self.posts.append((url, json))
        return FakeResponse({"data": {"task_id": "task-1"}})

    async def get(self, url, **kwargs):
        self.gets.append(url)
        if url == "https://media.test/scene.mp4":
            return FakeResponse(content=self.media, content_type="video/mp4")
        if url.endswith("/task-1"):
            return FakeResponse({"data": {"task_status": "succeed", "task_result": {
                "videos": [{"url": "https://media.test/scene.mp4"}]
            }}})
        return FakeResponse(status=404)


def load_avatar_transport():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {
        "_run_kling_avatar_result_bytes", "_create_and_poll_i2v_bytes",
        "_poll_video_task_for_bytes", "_download_binary_from_url", "_extract_first_url",
    }
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec")
    fake_httpx = SimpleNamespace(AsyncClient=FakeClient)

    async def no_delay(_delay):
        pass

    env = {
        "httpx": fake_httpx, "asyncio": SimpleNamespace(sleep=no_delay),
        "KLING_API_KEY": "test-key", "COMET_API_KEY": "",
        "COMET_BASE_URL": "https://api.test",
        "KLING_AVATAR_CREATE_PATH": "/avatar/image2video",
        "KLING_AVATAR_STATUS_PATH": "/avatar/image2video/{id}",
        "KLING_AVATAR_MODE": "std", "KLING_AVATAR_PROMPT": "Speak",
        "VOCAL_CLIP_KLING_MAX_WAIT_S": 30, "VIDEO_POLL_DELAY_S": 0,
        "_telegram_file_public_url": lambda url: url,
        "_api_error_preview": lambda resp: resp.text[:100],
        "log": SimpleNamespace(warning=lambda *a: None, info=lambda *a: None),
        "base64": base64,
        "json": __import__("json"),
        "time": __import__("time"),
    }
    exec(code, env)
    return env


class KlingAvatarTransportTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        FakeClient.media = FAKE_MP4

    def test_single_avatar_scene_returns_downloaded_mp4_without_telegram_delivery(self):
        env = load_avatar_transport()
        video = asyncio.run(env["_run_kling_avatar_result_bytes"](
            b"photo", "https://media.test/audio.mp3", "audio.mp3", "audio/mpeg", "female sings", 30
        ))
        self.assertEqual(FAKE_MP4, video)
        client, = FakeClient.instances
        self.assertEqual(1, len(client.posts))
        self.assertEqual("https://api.test/avatar/image2video", client.posts[0][0])
        payload = client.posts[0][1]
        self.assertEqual("https://media.test/audio.mp3", payload["sound_file"])
        self.assertEqual("female sings", payload["prompt"])
        self.assertEqual(base64.b64encode(b"photo").decode(), payload["image"])
        self.assertIn("https://media.test/scene.mp4", client.gets)

    def test_avatar_scene_rejects_non_video_body_before_next_paid_scene(self):
        FakeClient.media = b'{"message":"not a video"}' + b" " * 1024
        env = load_avatar_transport()
        with self.assertRaises(RuntimeError):
            asyncio.run(env["_run_kling_avatar_result_bytes"](
                b"photo", "https://media.test/audio.mp3", "audio.mp3", "audio/mpeg", "sings", 30
            ))
        self.assertEqual(1, len(FakeClient.instances[0].posts))


if __name__ == "__main__":
    unittest.main()
