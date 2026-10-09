import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_video_pipeline():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {"_concat_video_segments_sync", "_mux_video_audio_sync", "_ffmpeg_exe"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec")
    env = {
        "os": os, "shutil": shutil, "subprocess": subprocess,
        "tempfile": tempfile, "time": time,
        "PHOTO_CLIP_MAX_DURATION_S": 90, "PHOTO_CLIP_DEFAULT_DURATION_S": 15,
        "PHOTO_CLIP_SEND_BASE_IF_MUX_FAILS": False,
        "FFMPEG_MUX_TIMEOUT_S": 180, "FFMPEG_MUX_MAX_MB": 45,
        "FFMPEG_MUX_COPY_FIRST": True, "FFMPEG_MUX_AUDIO_BITRATE": "128k",
        "FFMPEG_MUX_REENCODE_PRESET": "ultrafast",
        "FFMPEG_MUX_SCALE_HEIGHT": 720, "FFMPEG_MUX_FPS": 24, "FFMPEG_MUX_CRF": 32,
        "log": SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    }
    exec(code, env)
    return env


def load_lipsync_splicer():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {"_extract_video_interval_file_sync", "_replace_video_interval_file_sync"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    env = {
        "os": os, "shutil": shutil, "subprocess": subprocess, "tempfile": tempfile,
        "FFMPEG_MUX_REENCODE_PRESET": "ultrafast", "FFMPEG_MUX_CRF": 23,
        "FFMPEG_MUX_THREADS": 1, "FFMPEG_MUX_TIMEOUT_S": 180,
        "_ffmpeg_exe": lambda: shutil.which("ffmpeg"),
        "log": SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class VocalClipAssemblyTests(unittest.TestCase):
    def test_two_scenes_join_and_original_audio_yield_one_playable_mp4(self):
        env = load_video_pipeline()
        ffmpeg = shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as td:
            scenes = []
            for color in ("red", "blue"):
                path = Path(td) / (color + ".mp4")
                subprocess.run([
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=12",
                    "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path),
                ], check=True, capture_output=True)
                scenes.append(path.read_bytes())
            audio = Path(td) / "song.mp3"
            subprocess.run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
                "-c:a", "libmp3lame", str(audio),
            ], check=True, capture_output=True)
            joined = env["_concat_video_segments_sync"](scenes, 10)
            self.assertTrue(joined)
            result = env["_mux_video_audio_sync"](joined, audio.read_bytes(), 10)
            self.assertTrue(result)
            final = Path(td) / "final.mp4"
            final.write_bytes(result)
            probe = subprocess.run([
                shutil.which("ffprobe"), "-v", "error", "-show_entries",
                "format=duration:stream=codec_type", "-of", "json", str(final),
            ], check=True, capture_output=True, text=True)
            info = json.loads(probe.stdout)
            self.assertEqual({"video", "audio"}, {s["codec_type"] for s in info["streams"]})
            self.assertAlmostEqual(10, float(info["format"]["duration"]), delta=0.5)
            self.assertLess(len(result), 45 * 1024 * 1024)

    def test_partial_lipsync_replaces_only_selected_interval_and_keeps_duration(self):
        env = load_lipsync_splicer()
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as td:
            original = Path(td) / "original.mp4"
            replacement_source = Path(td) / "replacement_source.mp4"
            replacement = Path(td) / "replacement.mp4"
            output = Path(td) / "spliced.mp4"
            subprocess.run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "color=c=red:s=160x90:r=12", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(original),
            ], check=True)
            subprocess.run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=160x90:r=12", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(replacement_source),
            ], check=True)
            self.assertEqual(str(replacement), env["_extract_video_interval_file_sync"](
                str(replacement_source), 0.0, 2.0, str(replacement),
            ))
            self.assertEqual(str(output), env["_replace_video_interval_file_sync"](
                str(original), str(replacement), 2.0, 4.0, 6.0, str(output),
            ))

            duration = float(subprocess.check_output([
                ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output),
            ], text=True).strip())
            self.assertAlmostEqual(6.0, duration, delta=0.25)

            def pixel(at_s):
                return subprocess.check_output([
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(at_s), "-i", str(output),
                    "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
                ])

            before, during = pixel(1.0), pixel(3.0)
            self.assertGreater(before[0], before[2])
            self.assertGreater(during[2], during[0])


if __name__ == "__main__":
    unittest.main()
