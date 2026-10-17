import ast
import asyncio
from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def _load_photo_clip_reference_boundary():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {
        "_telegram_file_public_url",
        "_cache_photo",
        "_get_cached_photo_url",
        "_run_kling_photo_clip_result",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    submitted = {}

    async def create_and_poll(_base_url, _api_key, create_payloads, *_args, **_kwargs):
        submitted["payload"] = create_payloads[0][1]
        return b"video"

    env = {
        "BOT_TOKEN": "test-token",
        "_photo_cache": {},
        "_photo_url_cache": {},
        "KLING_API_KEY": "test-key",
        "COMET_API_KEY": "",
        "COMET_BASE_URL": "https://api.test",
        "KLING_MODEL": "kling-v1",
        "PHOTO_CLIP_MODE": "std",
        "KLING_CREATE_PATH": "/kling/v1/videos/image2video",
        "KLING_STATUS_PATH": "/kling/v1/videos/{id}",
        "LUMA_MAX_WAIT_S": 30,
        "RUNWAY_MAX_WAIT_S": 30,
        "sniff_image_mime": lambda _raw: "image/jpeg",
        "_duration_for_engine": lambda _engine, seconds: seconds,
        "_photo_clip_prompt": lambda prompt, _duration: prompt,
        "_create_and_poll_i2v_bytes": create_and_poll,
        "base64": __import__("base64"),
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"),
        env,
    )
    return env, submitted


class KlingPhotoClipImageReferenceTests(unittest.TestCase):
    def test_kling_photo_clip_submits_telegram_https_url_not_data_url(self):
        env, submitted = _load_photo_clip_reference_boundary()
        env["_cache_photo"](42, b"portrait", "photos/portrait.jpg")

        asyncio.run(env["_run_kling_photo_clip_result"](
            b"portrait", "cinematic portrait", 10, "9:16", env["_get_cached_photo_url"](42)
        ))

        self.assertEqual(
            "https://api.telegram.org/file/bottest-token/photos/portrait.jpg",
            submitted["payload"]["image"],
        )
