import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from property_video_audio import (
    create_narration_plan,
    manual_narration_plan,
    mix_property_audio,
    parse_narration_plan,
    recover_music_track,
)
from property_video_pipeline import plan_property_scenes


class PropertyVideoAudioTests(unittest.TestCase):
    def test_narration_is_scene_bounded_and_factual(self):
        scenes = plan_property_scenes(5, 20, "kling", "full")

        async def writer(prompt, **_kwargs):
            self.assertIn("Never invent", prompt)
            return '{"scenes":[{"text":"Панорамный бассейн и вид"},{"text":"Светлая кухня с островом"},{"text":"Просторная гостиная"},{"text":"Спокойная светлая спальня"}]}'

        plan = asyncio.run(create_narration_plan(
            [{"space": "terrace_pool", "summary": "pool"}] * 5,
            scenes, "ru", "male", writer=writer,
        ))
        self.assertEqual(len(plan["segments"]), 4)
        self.assertEqual(plan["voice"], "male")
        self.assertAlmostEqual(sum(item["duration"] for item in plan["segments"]), 20)

    def test_invalid_model_json_falls_back_without_invented_specifics(self):
        scenes = plan_property_scenes(3, 10, "kling", "interior")

        async def writer(*_args, **_kwargs):
            return "not json"

        plan = asyncio.run(create_narration_plan(
            [{"space": "living_room", "summary": ""}] * 3,
            scenes, "ru", "female", writer=writer,
        ))
        self.assertEqual(len(plan["segments"]), 2)
        self.assertNotIn("приват", plan["full_text"].lower())
        self.assertNotIn("соврем", plan["full_text"].lower())
        self.assertNotIn("свет", plan["full_text"].lower())

    def test_manual_script_is_distributed_across_scenes(self):
        scenes = plan_property_scenes(3, 10, "kling", "full")
        plan = manual_narration_plan("Первая сцена. Вторая сцена.", scenes, "ru", "female")
        self.assertEqual([item["text"] for item in plan["segments"]], ["Первая сцена.", "Вторая сцена."])

    def test_parser_rejects_missing_scene(self):
        scenes = plan_property_scenes(5, 20, "kling", "full")
        self.assertIsNone(parse_narration_plan('{"scenes":[{"text":"one"}]}', scenes, "en", "female"))

    def test_fallback_does_not_invent_pool_for_terrace_label(self):
        scenes = plan_property_scenes(1, 8, "kling", "exterior")

        async def writer(*_args, **_kwargs):
            return "invalid"

        plan = asyncio.run(create_narration_plan(
            [{"space": "terrace_pool", "summary": "patio"}], scenes,
            "en", "female", writer=writer,
        ))
        self.assertNotIn("pool", plan["full_text"].lower())

    def test_music_and_voice_are_mixed_into_exact_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video, music, voice, output = (root / name for name in ("v.mp4", "m.wav", "voice.wav", "out.mp4"))
            subprocess.run([
                "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ], check=True, capture_output=True)
            for path, frequency in ((music, 220), (voice, 440)):
                subprocess.run([
                    "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={frequency}:duration=2", "-ar", "48000", str(path),
                ], check=True, capture_output=True)
            mix_property_audio(str(video), str(output), 2, music_path=str(music), voice_path=str(voice))
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                "-of", "json", str(output),
            ], check=True, capture_output=True, text=True).stdout
            self.assertIn('"codec_type": "audio"', probe)
            self.assertIn('"duration": "2.000000"', probe)

    def test_no_sound_removes_provider_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "provider.mp4"
            output = root / "silent.mp4"
            subprocess.run([
                "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest",
                "-c:v", "libx264", "-c:a", "aac", str(source),
            ], check=True, capture_output=True)
            mix_property_audio(str(source), str(output), 1)
            streams = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output),
            ], check=True, capture_output=True, text=True).stdout.splitlines()
            self.assertEqual(streams, ["video"])

    def test_suno_recovery_prefers_completed_audio_over_cover_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tone = root / "tone.mp3"
            subprocess.run([
                "ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
                "sine=frequency=330:duration=1", str(tone),
            ], check=True, capture_output=True)
            requested = []

            def extract(value):
                return value if isinstance(value, str) and value.startswith("https://") else None

            async def download(_client, url, **_kwargs):
                requested.append(url)
                return tone.read_bytes()

            fake_main = SimpleNamespace(
                SUNO_API_KEY="key", SUNO_BASE_URL="https://suno.test",
                SUNO_STATUS_PATH="/status/{id}", _extract_first_url=extract,
                _download_binary_from_url=download,
            )

            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {
                        "status": "completed", "url": "https://cdn.test/cover.jpg",
                        "audio_url": "https://cdn.test/final.mp3",
                    }

            class Client:
                async def __aenter__(self): return self
                async def __aexit__(self, *_args): return False
                async def get(self, *_args, **_kwargs): return Response()

            with patch.dict(sys.modules, {"main": fake_main}), patch("httpx.AsyncClient", return_value=Client()):
                path = asyncio.run(recover_music_track("task-123", str(root / "audio")))
            self.assertEqual(requested, ["https://cdn.test/final.mp3"])
            self.assertTrue(Path(path).is_file())


if __name__ == "__main__":
    unittest.main()
