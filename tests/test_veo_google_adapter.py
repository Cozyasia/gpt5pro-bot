import base64
import unittest
from unittest.mock import patch

from neyrobot_prod.veo_google_adapter import (
    build_generate_payload,
    build_extend_payload,
    extract_operation_name,
)


class GoogleVeoAdapterTests(unittest.TestCase):
    def test_initial_payload_uses_official_native_video_shape(self):
        payload = build_generate_payload("Русская реплика", aspect_ratio="9:16")
        self.assertEqual(payload["instances"][0]["prompt"], "Русская реплика")
        self.assertEqual(payload["parameters"]["aspectRatio"], "9:16")
        self.assertEqual(payload["parameters"]["resolution"], "720p")
        self.assertEqual(payload["parameters"]["durationSeconds"], 8)
        self.assertEqual(payload["parameters"]["numberOfVideos"], 1)

    def test_extension_payload_embeds_previous_video_and_keeps_audio_native(self):
        payload = build_extend_payload(b"mp4-bytes", "Продолжи действие")
        video = payload["instances"][0]["video"]["inlineData"]
        self.assertEqual(video["mimeType"], "video/mp4")
        self.assertEqual(base64.b64decode(video["data"]), b"mp4-bytes")
        self.assertEqual(payload["parameters"], {"numberOfVideos": 1, "resolution": "720p"})

    def test_operation_name_is_required(self):
        self.assertEqual(extract_operation_name({"name": "operations/123"}), "operations/123")
        with self.assertRaises(ValueError):
            extract_operation_name({"status": "queued"})

    def test_extend_submits_once_then_polls_until_native_result(self):
        from neyrobot_prod.veo_google_adapter import GoogleVeoClient

        class Response:
            def __init__(self, payload, *, status_code=200, content=b""):
                self._payload = payload
                self.status_code = status_code
                self.text = str(payload)
                self.content = content

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise AssertionError(self.text)

        class FakeClient:
            def __init__(self, responses):
                self.responses = iter(responses)
                self.post_calls = []
                self.get_calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, **kwargs):
                self.post_calls.append((url, kwargs))
                return next(self.responses)

            async def get(self, url, **kwargs):
                self.get_calls.append((url, kwargs))
                return next(self.responses)

        encoded = base64.b64encode(b"native-cumulative-mp4").decode("ascii")
        submit_client = FakeClient([Response({"name": "operations/extend-1"})])
        poll_client = FakeClient([
            Response({"done": False}),
            Response({
                "done": True,
                "response": {"generateVideoResponse": {
                    "generatedSamples": [{"video": {"inlineData": {"data": encoded}}}]
                }},
            }),
        ])

        async def no_sleep(_seconds):
            return None

        async def run():
            client = GoogleVeoClient(
                "test-key", poll_interval_s=0, max_wait_s=5,
                model="veo-3.1-fast-generate-preview",
            )
            with patch(
                "neyrobot_prod.veo_google_adapter.httpx.AsyncClient",
                side_effect=[submit_client, poll_client],
            ), patch(
                "neyrobot_prod.veo_google_adapter._async_sleep",
                side_effect=no_sleep,
            ):
                return await client.extend(b"previous-mp4", "Продолжи")

        import asyncio
        result = asyncio.run(run())
        self.assertEqual(result, b"native-cumulative-mp4")
        self.assertEqual(len(submit_client.post_calls), 1)
        self.assertEqual(submit_client.post_calls[0][0],
                         "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-fast-generate-preview:predictLongRunning")
        self.assertEqual(len(poll_client.get_calls), 2)
