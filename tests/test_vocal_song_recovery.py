import ast
import asyncio
import contextlib
import hashlib
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_recovery(root):
    names = {
        "_vocal_artifact_path", "_prune_vocal_artifacts", "_save_vocal_artifact",
        "_load_vocal_artifact", "_photo_clip_target_duration", "_vocal_clip_provider_cost_usd",
        "_start_vocal_clip", "_on_vocal_artifact_callback",
    }
    nodes = [
        node for node in ast.parse(MAIN.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    env = {
        "os": os, "re": re, "uuid": uuid, "time": time, "contextlib": contextlib,
        "asyncio": asyncio, "hashlib": hashlib,
        "VOCAL_CLIP_ARTIFACT_DIR": str(root),
        "PHOTO_CLIP_DEFAULT_DURATION_S": 15, "PHOTO_CLIP_MAX_DURATION_S": 90,
        "PHOTO_CLIP_SCENE_SECONDS": 10, "PHOTO_CLIP_MAX_SCENES": 9,
        "FACESWAP_FACE_DETECTION_ENABLED": False,
        "SUNO_ENABLED": True, "SUNO_API_KEY": "test-key",
        "VOCAL_CLIP_KLING_MAX_WAIT_S": 1200,
        "FFMPEG_MUX_TIMEOUT_S": 180,
        "VOCAL_CLIP_UNIT_COST_USD": 1.50, "AVATAR_UNIT_COST_USD": 0.65,
        "ChatAction": SimpleNamespace(RECORD_VIDEO="record_video"),
        "Update": object, "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "_vocal_clip_background_jobs": set(),
        "_vocal_clip_role_plan": lambda *_: {"mode": "solo"},
        "log": SimpleNamespace(exception=lambda *args: None),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


class VocalSongRecoveryTests(unittest.TestCase):
    def test_failed_video_can_be_sent_from_saved_file_only_by_its_owner(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_recovery(root)
            token = "abcdef123456"
            env["_save_vocal_artifact"](42, token, "video", b"\x00\x00\x00\x18ftyp" + b"v" * 4096)
            sent, messages = [], []

            async def answer(*_args):
                pass

            async def reply_text(message, **_kwargs):
                messages.append(message)

            async def send_video(_update, data, _caption):
                sent.append(data)

            env["_reply_video_bytes"] = send_video
            context = SimpleNamespace(user_data={})
            def update_for(user):
                return SimpleNamespace(callback_query=SimpleNamespace(
                    data=f"mvfile:video:{token}", from_user=SimpleNamespace(id=user),
                    message=SimpleNamespace(reply_text=reply_text), answer=answer,
                ))

            asyncio.run(env["_on_vocal_artifact_callback"](update_for(43), context))
            self.assertEqual([], sent)
            asyncio.run(env["_on_vocal_artifact_callback"](update_for(42), context))
            self.assertEqual(1, len(sent))
            self.assertFalse(Path(env["_vocal_artifact_path"](42, token, "video")).exists())

    def test_full_song_is_persisted_per_user_and_not_shared(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_recovery(root)
            token, data = "abcdef012345", b"ID3" + b"x" * 4096
            env["_save_vocal_artifact"](42, token, "audio", data)
            self.assertEqual(data, env["_load_vocal_artifact"](42, token, "audio"))
            self.assertIsNone(env["_load_vocal_artifact"](43, token, "audio"))
            with self.assertRaises(ValueError):
                env["_vocal_artifact_path"](42, "../../outside", "audio")
            path = env["_vocal_artifact_path"](42, token, "audio")
            old = time.time() - 8 * 86400
            os.utime(path, (old, old))
            self.assertIsNone(env["_load_vocal_artifact"](42, token, "audio"))

    def test_selected_song_skips_new_suno_generation(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_recovery(root)
            token = "123456abcdef"
            env["_save_vocal_artifact"](42, token, "audio", b"ID3" + b"s" * 4096)
            messages, billed, provider_calls = [], [], []

            async def reply_text(message, **kwargs):
                messages.append(message)

            async def try_pay(*args, **kwargs):
                billed.append(await args[5]())

            async def suno(*_args):
                provider_calls.append("suno")
                return None

            async def scene(*_args, **_kwargs):
                provider_calls.append("kling")
                return b"\x00\x00\x00\x18ftyp" + b"v" * 4096

            async def result(*_args):
                provider_calls.append("sent")

            async def immediate_thread(fn, *args):
                return fn(*args)

            env.update({
                "_try_pay_then_do": try_pay, "_run_suno_music_result_bytes": suno,
                "_trim_audio_for_vocal_clip": lambda audio, duration: asyncio.sleep(0, result=audio),
                "_extract_audio_segment_bytes": lambda *_: asyncio.sleep(0, result=b"ID3" + b"m" * 1024),
                "_upload_bytes_to_telegram_file_url": lambda *_: asyncio.sleep(0, result="https://example.test/a.mp3"),
                "_vocal_scene_role_prompt": lambda *_: "scene",
                "_run_kling_avatar_result_bytes": scene,
                "_concat_video_segments_sync": lambda segs, *_: segs[0],
                "_mux_video_audio_sync": lambda *_: b"\x00\x00\x00\x18ftyp" + b"m" * 4096,
                "_reply_video_bytes": result,
                "asyncio": SimpleNamespace(to_thread=immediate_thread, wait_for=asyncio.wait_for),
            })
            update = SimpleNamespace(
                effective_message=SimpleNamespace(reply_text=reply_text),
                effective_user=SimpleNamespace(id=42),
                effective_chat=SimpleNamespace(id=42),
            )
            context = SimpleNamespace(
                user_data={"vocal_source_token": token},
                bot=SimpleNamespace(send_chat_action=lambda *_: asyncio.sleep(0)),
            )
            asyncio.run(env["_start_vocal_clip"](update, context, b"photo", "Я пою, 10 секунд"))
            self.assertEqual([True], billed)
            self.assertEqual(["kling", "sent"], provider_calls)
            self.assertNotIn("vocal_source_token", context.user_data)

    def test_full_suno_song_survives_failed_video_upload_without_new_provider_call(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_recovery(root)
            full_song = b"ID3" + b"original-vocal-" * 400
            events, messages, billed = [], [], []

            async def reply_text(message, **kwargs):
                messages.append((message, kwargs))

            async def suno(*_args):
                events.append("suno")
                return full_song

            async def send_song(_message, data, _token):
                self.assertEqual(full_song, data)
                events.append("full-song")

            async def scene(*_args, **_kwargs):
                events.append("kling")
                return b"\x00\x00\x00\x18ftyp" + b"v" * 4096

            async def failed_send(*_args):
                events.append("video-upload")
                raise TimeoutError("Telegram upload timed out")

            async def try_pay(*args, **kwargs):
                billed.append(await args[5]())

            async def immediate_thread(fn, *args):
                return fn(*args)

            env.update({
                "_try_pay_then_do": try_pay, "_run_suno_music_result_bytes": suno,
                "_send_vocal_song_file": send_song,
                "_trim_audio_for_vocal_clip": lambda audio, duration: asyncio.sleep(0, result=audio[:2048]),
                "_extract_audio_segment_bytes": lambda *_: asyncio.sleep(0, result=b"ID3" + b"x" * 1024),
                "_upload_bytes_to_telegram_file_url": lambda *_: asyncio.sleep(0, result="https://example.test/a.mp3"),
                "_vocal_scene_role_prompt": lambda *_: "scene",
                "_run_kling_avatar_result_bytes": scene,
                "_concat_video_segments_sync": lambda segs, *_: segs[0],
                "_mux_video_audio_sync": lambda *_: b"\x00\x00\x00\x18ftyp" + b"m" * 4096,
                "_reply_video_bytes": failed_send,
                "asyncio": SimpleNamespace(to_thread=immediate_thread, wait_for=asyncio.wait_for),
                "InlineKeyboardButton": lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
                "InlineKeyboardMarkup": lambda rows: SimpleNamespace(rows=rows),
            })
            update = SimpleNamespace(
                effective_message=SimpleNamespace(reply_text=reply_text),
                effective_user=SimpleNamespace(id=42),
                effective_chat=SimpleNamespace(id=42),
            )
            context = SimpleNamespace(
                user_data={},
                bot=SimpleNamespace(send_chat_action=lambda *_: asyncio.sleep(0)),
            )
            asyncio.run(env["_start_vocal_clip"](update, context, b"photo", "Я пою, 10 секунд"))
            self.assertEqual([False], billed, "no charge on failed delivery")
            self.assertEqual(["suno", "full-song", "kling", "video-upload"], events)
            audio_files = list((Path(root) / "42").glob("*_audio.mp3"))
            video_files = list((Path(root) / "42").glob("*_video.mp4"))
            self.assertEqual(1, len(audio_files))
            self.assertEqual(full_song, audio_files[0].read_bytes())
            self.assertEqual(1, len(video_files))
            retry_buttons = [b.callback_data for row in messages[-1][1]["reply_markup"].rows for b in row]
            self.assertTrue(any(data.startswith("mvfile:video:") for data in retry_buttons))


if __name__ == "__main__":
    unittest.main()
