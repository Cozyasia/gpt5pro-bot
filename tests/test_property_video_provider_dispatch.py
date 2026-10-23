import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from property_video_pipeline import render_scene, render_scene_to_file


class PropertyVideoProviderDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.photo = Path(self.tmp.name) / "reference.jpg"
        self.photo.write_bytes(b"fake-jpeg")

    def tearDown(self):
        self.tmp.cleanup()

    def test_veo_records_operation_and_returns_bytes(self):
        fake_client = SimpleNamespace(
            submit_initial=AsyncMock(return_value="operations/veo-1"),
            poll_bytes=AsyncMock(return_value=b"veo-mp4"),
        )
        seen = []

        async def run():
            with patch.dict(os.environ, {"GEMINI_VIDEO_API_KEY": "test-key"}, clear=False), \
                 patch("property_video_pipeline.GoogleVeoClient", return_value=fake_client):
                return await render_scene("veo", str(self.photo), "property", 8, on_task_id=seen.append)

        self.assertEqual(asyncio.run(run()), b"veo-mp4")
        self.assertEqual(seen, ["operations/veo-1"])

    def test_seedance_records_task_id_and_returns_bytes(self):
        seen = []

        async def fake_seedance(**kwargs):
            kwargs["on_task_id"]("seedance-1")
            return b"seedance-mp4"

        async def run():
            with patch.dict(os.environ, {"COMET_API_KEY": "test-key"}, clear=False), \
                 patch("property_video_pipeline.seedance_generate", side_effect=fake_seedance):
                return await render_scene("seedance", str(self.photo), "property", 10, on_task_id=seen.append)

        self.assertEqual(asyncio.run(run()), b"seedance-mp4")
        self.assertEqual(seen, ["seedance-1"])

    def test_kling_uses_existing_production_transport(self):
        seen = []

        async def fake_kling(*args, **kwargs):
            kwargs["on_task_id"]("kling-1")
            return b"kling-mp4"

        fake_main = SimpleNamespace(
            _run_kling_photo_clip_result=AsyncMock(side_effect=fake_kling),
            _provider_input_url_from_file=lambda path, filename: "https://app.test/provider-input/reference.jpg",
        )

        async def run():
            with patch.dict(os.environ, {"COMET_API_KEY": "test-key"}, clear=False), \
                 patch.dict("sys.modules", {"main": fake_main}):
                return await render_scene("kling", str(self.photo), "property", 10, on_task_id=seen.append)

        self.assertEqual(asyncio.run(run()), b"kling-mp4")
        fake_main._run_kling_photo_clip_result.assert_awaited_once()
        self.assertEqual(
            fake_main._run_kling_photo_clip_result.await_args.kwargs["image_url"],
            "https://app.test/provider-input/reference.jpg",
        )
        self.assertEqual(seen, ["kling-1"])

    def test_kling_passes_adjacent_reference_as_last_frame(self):
        seen = []
        next_photo = Path(self.tmp.name) / "next.jpg"
        next_photo.write_bytes(b"next-jpeg")

        async def fake_kling(*args, **kwargs):
            kwargs["on_task_id"]("kling-transition-1")
            return b"kling-mp4"

        fake_main = SimpleNamespace(
            _run_kling_photo_clip_result=AsyncMock(side_effect=fake_kling),
            _provider_input_url_from_file=lambda path, filename: f"https://app.test/provider-input/{Path(path).name}",
        )

        async def run():
            with patch.dict(os.environ, {"COMET_API_KEY": "test-key"}, clear=False), \
                 patch.dict("sys.modules", {"main": fake_main}):
                return await render_scene(
                    "kling", str(self.photo), "property", 10,
                    on_task_id=seen.append, last_photo_path=str(next_photo),
                )

        self.assertEqual(asyncio.run(run()), b"kling-mp4")
        kwargs = fake_main._run_kling_photo_clip_result.await_args.kwargs
        self.assertEqual(kwargs["image_tail_url"], "https://app.test/provider-input/next.jpg")
        self.assertEqual(seen, ["kling-transition-1"])

    def test_render_scene_to_file_persists_and_does_not_keep_scene_bytes(self):
        async def run():
            with patch("property_video_pipeline.render_scene", new=AsyncMock(return_value=b"x" * 1024)):
                return await render_scene_to_file(
                    "seedance", str(self.photo), "property", 10,
                    str(Path(self.tmp.name) / "scene.mp4"),
                )

        path = asyncio.run(run())
        self.assertTrue(Path(path).is_file())
        self.assertEqual(Path(path).stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
