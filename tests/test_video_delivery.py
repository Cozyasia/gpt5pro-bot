import ast
import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_delivery():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {"_reply_video_bytes", "_mark_video_sent_once", "_cleanup_sent_video_keys", "_video_result_key"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    env = {
        "BytesIO": BytesIO,
        "InputFile": lambda data: data,
        "Update": object,
        "VIDEO_RESULT_SEND_AS_DOCUMENT": True,
        "VIDEO_RESULT_DEDUPE_TTL_S": 900,
        "VIDEO_SEND_WRITE_TIMEOUT_S": 180,
        "_SENT_VIDEO_KEYS": {},
        "log": SimpleNamespace(info=lambda *a, **k: None),
    }
    import hashlib
    import time
    env.update(hashlib=hashlib, time=time)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


class VideoDeliveryTests(unittest.TestCase):
    def test_large_upload_gets_extended_timeout_and_can_retry_after_failure(self):
        env = load_delivery()
        calls = []

        async def reply_document(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise TimeoutError("write timed out")

        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=123),
            effective_message=SimpleNamespace(reply_document=reply_document),
        )
        payload = b"\x00\x00\x00\x18ftyp" + b"x" * 1024
        with self.assertRaises(TimeoutError):
            asyncio.run(env["_reply_video_bytes"](update, payload, "Клип"))
        asyncio.run(env["_reply_video_bytes"](update, payload, "Клип"))
        self.assertEqual(2, len(calls))
        self.assertGreaterEqual(calls[0]["write_timeout"], 120)
        self.assertGreaterEqual(calls[0]["read_timeout"], 60)
        asyncio.run(env["_reply_video_bytes"](update, payload, "Клип"))
        self.assertEqual(2, len(calls), "a confirmed upload must be suppressed")


if __name__ == "__main__":
    unittest.main()
