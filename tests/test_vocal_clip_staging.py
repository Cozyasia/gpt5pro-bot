import ast
import asyncio
import contextlib
import hashlib
import math
from pathlib import Path
import re
import unittest
from types import SimpleNamespace


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_entry_points():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_photo_clip_target_duration", "_start_vocal_clip"}
    ]
    module = ast.Module(body=selected, type_ignores=[])
    code = compile(ast.fix_missing_locations(module), str(MAIN), "exec")
    env = {
        "asyncio": asyncio, "hashlib": hashlib, "math": math, "re": re,
        "Update": object, "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "PHOTO_CLIP_DEFAULT_DURATION_S": 15, "PHOTO_CLIP_MAX_DURATION_S": 90,
        "PHOTO_CLIP_SCENE_SECONDS": 10, "PHOTO_CLIP_MAX_SCENES": 9,
        "FACESWAP_FACE_DETECTION_ENABLED": False,
        "_vocal_clip_role_plan": lambda *_: {"mode": "solo"},
        "_vocal_clip_background_jobs": set(),
        "VOCAL_CLIP_UNIT_COST_USD": 1.50,
        "contextlib": contextlib,
        "SUNO_ENABLED": True, "SUNO_API_KEY": "test-key",
        "ChatAction": SimpleNamespace(RECORD_VIDEO="record_video"),
        "log": SimpleNamespace(exception=lambda *args: None),
    }
    exec(code, env)
    return env


class VocalClipStagingTests(unittest.TestCase):
    def test_long_vocal_request_is_rejected_before_billing_or_provider_call(self):
        env = load_entry_points()
        messages = []
        billed = []

        async def reply_text(message):
            messages.append(message)

        async def try_pay(*args, **kwargs):
            billed.append((args, kwargs))

        env["_try_pay_then_do"] = try_pay
        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(user_data={})

        asyncio.run(env["_start_vocal_clip"](update, context, b"photo", "Дуэт, 60 секунд"))

        self.assertEqual([], billed)
        self.assertEqual(1, len(messages))
        self.assertIn("60", messages[0])
        self.assertIn("10", messages[0])

    def test_short_vocal_request_keeps_one_scene_billing_path(self):
        env = load_entry_points()
        billed = []

        async def reply_text(_message):
            self.fail("Short request should proceed to payment path")

        async def try_pay(*args, **kwargs):
            billed.append((args, kwargs))

        env["_try_pay_then_do"] = try_pay
        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(user_data={})

        asyncio.run(env["_start_vocal_clip"](update, context, b"photo", "Клип, 10 секунд"))

        self.assertEqual(1, len(billed))
        self.assertEqual(1, billed[0][1]["remember_payload"]["scenes"])
        self.assertEqual(1.50, billed[0][0][4])

    def test_provider_error_details_stay_out_of_user_message(self):
        env = load_entry_points()
        messages = []
        logged = []

        async def reply_text(message):
            messages.append(message)

        async def send_chat_action(*_args):
            pass

        async def fail_suno(*_args):
            raise RuntimeError('{"provider_secret":"private detail"}')

        async def try_pay(*args, **kwargs):
            await args[5]()

        env.update({
            "_try_pay_then_do": try_pay,
            "_run_suno_music_result_bytes": fail_suno,
            "log": SimpleNamespace(exception=lambda *args: logged.append(args)),
        })
        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=send_chat_action))

        asyncio.run(env["_start_vocal_clip"](update, context, b"photo", "Клип, 10 секунд"))

        self.assertTrue(logged)
        self.assertIn("private detail", str(logged[0]))
        self.assertNotIn("private detail", "\n".join(messages))
        self.assertIn("не получился", messages[-1])


if __name__ == "__main__":
    unittest.main()
