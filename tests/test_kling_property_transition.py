import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("PUBLIC_URL", "https://test.onrender.com")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
import main


class KlingPropertyTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_property_render_sends_next_reference_as_image_tail(self):
        main.KLING_API_KEY = "test-key"
        main.COMET_API_KEY = "test-key"
        with patch.object(
            main,
            "_create_and_poll_i2v_bytes",
            new=AsyncMock(return_value=b"video"),
        ) as submit:
            result = await main._run_kling_photo_clip_result(
                b"first-jpeg",
                "continuous real-estate walkthrough",
                5,
                "9:16",
                image_url="https://example.test/first.jpg",
                image_tail_url="https://example.test/last.jpg",
                prompt_mode="property",
            )

        self.assertEqual(result, b"video")
        payload = submit.await_args.args[2][0][1]
        self.assertEqual(payload["image"], "https://example.test/first.jpg")
        self.assertEqual(payload["image_tail"], "https://example.test/last.jpg")
