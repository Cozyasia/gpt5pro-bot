import ast
import asyncio
import contextlib
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_functions(names, extra=None):
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    env = {
        "asyncio": asyncio,
        "contextlib": contextlib,
        "hashlib": hashlib,
        "os": os,
        "re": re,
        "shutil": shutil,
        "subprocess": subprocess,
        "tempfile": tempfile,
        "time": time,
        "uuid": uuid,
        "Update": object,
        "log": SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None),
    }
    env.update(extra or {})
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"),
        env,
    )
    return env


class MusicVideoMemorySafetyTests(unittest.TestCase):
    def test_mux_preserves_native_dimensions_and_bounds_ffmpeg_threads(self):
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x18ftyp" + b"v" * 4096)
            return SimpleNamespace(returncode=0)

        env = load_functions(
            {"_mux_video_audio_files_sync"},
            {
                "PHOTO_CLIP_MAX_DURATION_S": 90,
                "PHOTO_CLIP_DEFAULT_DURATION_S": 15,
                "FFMPEG_MUX_TIMEOUT_S": 180,
                "FFMPEG_MUX_MAX_MB": 45,
                "FFMPEG_MUX_COPY_FIRST": False,
                "FFMPEG_MUX_AUDIO_BITRATE": "128k",
                "FFMPEG_MUX_REENCODE_PRESET": "ultrafast",
                "FFMPEG_MUX_FPS": 24,
                "FFMPEG_MUX_MAX_LONG_EDGE": 2160,
                "FFMPEG_MUX_THREADS": 1,
                "_ffmpeg_exe": lambda: "ffmpeg",
                "subprocess": SimpleNamespace(
                    run=fake_run,
                    DEVNULL=subprocess.DEVNULL,
                    TimeoutExpired=subprocess.TimeoutExpired,
                ),
            },
        )
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "joined.mp4"
            audio = Path(td) / "song.mp3"
            output = Path(td) / "final.mp4"
            video.write_bytes(b"v" * 8192)
            audio.write_bytes(b"a" * 4096)

            result = env["_mux_video_audio_files_sync"](str(video), str(audio), 30, str(output))

        self.assertEqual(str(output), result)
        command = calls[-1]
        rendered = " ".join(command)
        self.assertNotIn("3840", rendered)
        self.assertIn("2160", rendered)
        self.assertIn("min(iw", rendered)
        self.assertIn("min(ih", rendered)
        self.assertIn("-threads", command)
        self.assertEqual("1", command[command.index("-threads") + 1])
        self.assertIn("-filter_threads", command)

    def test_video_artifact_is_copied_and_validated_without_reading_it(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_functions(
                {
                    "_vocal_artifact_path", "_prune_vocal_artifacts",
                    "_save_vocal_artifact_file", "_load_vocal_artifact_path",
                },
                {"VOCAL_CLIP_ARTIFACT_DIR": root},
            )
            source = Path(root) / "source.mp4"
            payload = b"\x00\x00\x00\x18ftyp" + b"v" * 4096
            source.write_bytes(payload)

            saved = Path(env["_save_vocal_artifact_file"](42, "abcdef123456", "video", str(source)))
            source.unlink()

            self.assertEqual(payload, saved.read_bytes())
            self.assertEqual(str(saved), env["_load_vocal_artifact_path"](42, "abcdef123456", "video"))

    def test_telegram_file_delivery_keeps_input_file_streaming(self):
        input_files = []

        class FakeInputFile:
            def __init__(self, file_obj, filename=None, read_file_handle=True):
                self.file_obj = file_obj
                self.filename = filename
                self.read_file_handle = read_file_handle
                input_files.append(self)

        async def reply_document(*, document, **_kwargs):
            self.assertFalse(document.file_obj.closed)

        env = load_functions(
            {"_reply_video_file"},
            {
                "InputFile": FakeInputFile,
                "VIDEO_RESULT_SEND_AS_DOCUMENT": True,
                "VIDEO_SEND_WRITE_TIMEOUT_S": 180,
                "_video_result_key": lambda *_a, **_k: "key",
                "_mark_video_sent_once": lambda _key: False,
                "_SENT_VIDEO_KEYS": {},
            },
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "result.mp4"
            path.write_bytes(b"\x00\x00\x00\x18ftyp" + b"v" * 4096)
            update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=42),
                effective_message=SimpleNamespace(reply_document=reply_document),
            )
            asyncio.run(env["_reply_video_file"](update, str(path), "done"))

        self.assertEqual(1, len(input_files))
        self.assertFalse(input_files[0].read_file_handle)
        self.assertTrue(input_files[0].file_obj.closed)

    def test_vocal_pipeline_spills_each_scene_before_next_render(self):
        source = MAIN.read_text(encoding="utf-8")
        start = source.index("async def _start_vocal_clip")
        block = source[start:source.index("\nasync def ", start + 40)]
        self.assertNotIn("segments: list[bytes]", block)
        self.assertIn("_write_video_segment_file", block)
        self.assertIn("_extract_last_video_frame_file_sync", block)
        self.assertIn("async with _music_video_finalize_semaphore", block)
        self.assertIn("_save_vocal_artifact_file", block)
        self.assertIn("_reply_video_file", block)
        self.assertNotIn("final_bytes = fh.read()", block)

    def test_vocal_pipeline_requires_postprocess_lipsync_for_planned_intervals(self):
        source = MAIN.read_text(encoding="utf-8")
        start = source.index("async def _start_vocal_clip")
        block = source[start:source.index("\nasync def ", start + 40)]
        helper_start = source.index("async def _apply_kling_lipsync_to_scene_file")
        helper = source[helper_start:source.index("\nasync def ", helper_start + 40)]
        self.assertIn("_apply_kling_lipsync_to_scene_file", block)
        self.assertIn("_run_kling_lipsync_result_bytes", helper)
        self.assertIn("_replace_video_interval_file_sync", helper)
        self.assertIn("contract.lip_sync_start_s", helper)
        self.assertIn("contract.lip_sync_end_s", helper)
        self.assertNotIn("без принудительного lip-sync", block)

    def test_instrumental_pipeline_uses_the_same_file_safe_finalization(self):
        source = MAIN.read_text(encoding="utf-8")
        start = source.index("async def _start_photo_music_clip")
        block = source[start:source.index("\nasync def ", start + 40)]
        self.assertIn("_write_video_segment_file", block)
        self.assertIn("_concat_video_segment_files_sync", block)
        self.assertIn("async with _music_video_finalize_semaphore", block)
        self.assertIn("_mux_video_audio_files_sync", block)
        self.assertIn("_save_vocal_artifact_file", block)
        self.assertIn("_reply_video_file", block)
        self.assertNotIn("_concat_video_segments_sync, segments", block)
        self.assertNotIn("_mux_video_audio_sync, video_bytes", block)


if __name__ == "__main__":
    unittest.main()
