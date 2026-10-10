import ast
import asyncio
from io import BytesIO
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


SOURCE = Path("main.py").read_text(encoding="utf-8")


def _load_upload_helper():
    tree = ast.parse(SOURCE)
    names = {
        "_telegram_file_public_url",
        "_upload_bytes_to_telegram_file_url",
        "_upload_file_to_telegram_file_url",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]

    class FakeInputFile:
        def __init__(self, value, **_kwargs):
            self.value = value

    class FakeTimedOut(Exception):
        pass

    async def no_delay(_seconds):
        pass

    env = {
        "asyncio": SimpleNamespace(sleep=no_delay),
        "BytesIO": BytesIO,
        "InputFile": FakeInputFile,
        "TimedOut": FakeTimedOut,
        "Update": object,
        "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "BOT_TOKEN": "test-token",
        "VIDEO_SEND_WRITE_TIMEOUT_S": 120,
        "os": os,
        "log": SimpleNamespace(warning=lambda *_args: None),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "main.py", "exec"), env)
    return env


def test_music_video_telegram_artifact_upload_retries_send_and_get_file():
    start = SOURCE.index("async def _upload_bytes_to_telegram_file_url")
    end = SOURCE.index("\n\nasync def _text_to_public_mp3_url", start)
    fn = SOURCE[start:end]
    assert fn.count("for attempt in range(3):") >= 2
    assert "telegram reply_document timeout" in fn
    assert "telegram get_file timeout" in fn
    assert "read_timeout=60" in fn
    assert "write_timeout=60" in fn
    assert "bio = BytesIO(raw)" in fn
    assert fn.index("for attempt in range(3):") < fn.index("bio = BytesIO(raw)")


def test_music_video_background_job_has_progress_heartbeat_and_cleanup():
    start = SOURCE.index("async def _start_vocal_clip")
    end = SOURCE.index("\n\nasync def _start_text_video", start)
    fn = SOURCE[start:end]
    assert "timeout=150" in fn
    assert "Работа продолжается, бот не завис" in fn
    assert "heartbeat_stop.set()" in fn
    assert "heartbeat_task.cancel()" in fn
    assert "await heartbeat_task" in fn


class KeyframeFileUrlTests(unittest.TestCase):
    def test_retries_successful_get_file_until_path_is_available(self):
        env = _load_upload_helper()
        paths = iter(["", "", "documents/keyframe.png"])
        calls = []

        async def reply_document(**_kwargs):
            return SimpleNamespace(document=SimpleNamespace(file_id="keyframe-file-id"))

        async def get_file(file_id):
            calls.append(file_id)
            return SimpleNamespace(file_path=next(paths))

        update = SimpleNamespace(effective_message=SimpleNamespace(reply_document=reply_document))
        context = SimpleNamespace(bot=SimpleNamespace(get_file=get_file))

        result = asyncio.run(env["_upload_bytes_to_telegram_file_url"](
            update, context, b"png-bytes", "music_video_identity_keyframe.png"
        ))

        self.assertEqual(
            "https://api.telegram.org/file/bottest-token/documents/keyframe.png",
            result,
        )
        self.assertEqual(["keyframe-file-id"] * 3, calls)

    def test_file_upload_retries_successful_get_file_until_path_is_available(self):
        env = _load_upload_helper()
        paths = iter(["", "videos/lipsync-input.mp4"])
        calls = []

        async def reply_document(**_kwargs):
            return SimpleNamespace(document=SimpleNamespace(file_id="video-file-id"))

        async def get_file(file_id):
            calls.append(file_id)
            return SimpleNamespace(file_path=next(paths))

        update = SimpleNamespace(effective_message=SimpleNamespace(reply_document=reply_document))
        context = SimpleNamespace(bot=SimpleNamespace(get_file=get_file))
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            video.write(b"0" * 1024)
            video.flush()
            result = asyncio.run(env["_upload_file_to_telegram_file_url"](
                update, context, video.name, "scene_01.mp4"
            ))

        self.assertEqual(
            "https://api.telegram.org/file/bottest-token/videos/lipsync-input.mp4",
            result,
        )
        self.assertEqual(["video-file-id"] * 2, calls)
