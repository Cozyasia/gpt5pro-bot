import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from neyrobot_prod.veo_extend_15_pipeline import create_extended_video
from neyrobot_prod.veo_task_journal import read_job, write_job


class _ProviderVideo(bytes):
    def __new__(cls, payload, uri):
        obj = bytes.__new__(cls, payload)
        obj.provider_uri = uri
        return obj


class VeoExtendContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_provider_uri_is_forwarded_between_extensions(self):
        first_uri = "https://generativelanguage.googleapis.com/v1beta/files/initial"
        second_uri = "https://generativelanguage.googleapis.com/v1beta/files/extended"
        submit_initial = AsyncMock(return_value="initial-operation")
        poll = AsyncMock(return_value=_ProviderVideo(b"initial-video" * 200, first_uri))
        extend = AsyncMock(return_value=_ProviderVideo(b"cumulative-15" * 200, second_uri))
        with tempfile.TemporaryDirectory() as td:
            with patch(
                "neyrobot_prod.veo_extend_15_pipeline.probe_duration",
                side_effect=[15.0, 15.0, 15.0],
            ), patch(
                "neyrobot_prod.veo_extend_15_pipeline._render_delivery_video",
            ) as render:
                await create_extended_video(
                    directory=td,
                    prompt="Test",
                    duration_seconds=15,
                    base_url="https://api.cometapi.com",
                    api_key="key",
                    fast_model="veo3.1-fast",
                    poll=poll,
                    submit_initial=submit_initial,
                    extend_video=extend,
                    output_aspect_ratio="9:16",
                )
            render.assert_called_once()
            self.assertEqual(render.call_args.args[3], "9:16")
            self.assertEqual(extend.await_args.args[0], first_uri)
            self.assertEqual(
                (Path(td) / "extension_01.uri").read_text(), second_uri
            )

    async def test_multiple_extensions_feed_the_previous_cumulative_video(self):
        submit_initial = AsyncMock(return_value="initial-operation")
        poll = AsyncMock(return_value=b"initial-video" * 200)
        extend = AsyncMock(side_effect=[b"cumulative-15" * 200, b"cumulative-22" * 200])
        with tempfile.TemporaryDirectory() as td:
            with patch(
                "neyrobot_prod.veo_extend_15_pipeline.probe_duration",
                side_effect=[15.0, 22.0, 22.0, 22.0],
            ):
                result = await create_extended_video(
                    directory=td,
                    prompt="Test",
                    duration_seconds=22,
                    base_url="https://api.cometapi.com",
                    api_key="key",
                    fast_model="veo3.1-fast",
                    poll=poll,
                    submit_initial=submit_initial,
                    extend_video=extend,
                )
            self.assertEqual(result.name, "final_22s.mp4")
            self.assertEqual(submit_initial.await_count, 1)
            self.assertEqual(extend.await_count, 2)
            self.assertEqual(extend.await_args_list[0].args[0], b"initial-video" * 200)
            self.assertEqual(extend.await_args_list[1].args[0], b"cumulative-15" * 200)
            self.assertEqual(json.loads((Path(td) / "extension_01.json").read_text())["status"], "accepted")
            self.assertEqual(json.loads((Path(td) / "extension_02.json").read_text())["status"], "accepted")

    async def test_unconfigured_extension_stops_before_comet_extend(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("neyrobot_prod.veo_extend_15_pipeline.probe_duration", return_value=8.0):
                with self.assertRaises(RuntimeError) as error:
                    await create_extended_video(
                        directory=td,
                        prompt="Test",
                        duration_seconds=15,
                        base_url="https://api.cometapi.com",
                        api_key="key",
                        fast_model="veo3.1-fast",
                        poll=AsyncMock(return_value=b"x" * 2048),
                        submit_initial=AsyncMock(return_value="initial-task"),
                    )
            self.assertIn("native Veo Extend provider", str(error.exception))

    async def test_accepted_extension_is_resumed_from_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            (directory / "scene_01.mp4").write_bytes(b"x" * 2048)
            write_job(directory / "journal.json", {"scenes": {"1": {"state": "completed", "task_id": "initial"}}})
            (directory / "extension_01.mp4").write_bytes(b"y" * 2048)
            write_job(directory / "extension_01.json", {
                "status": "accepted", "step": 1,
                "source_artifact": "scene_01.mp4",
                "result_artifact": "extension_01.mp4",
            })
            with patch("neyrobot_prod.veo_extend_15_pipeline.probe_duration", return_value=15.0):
                result = await create_extended_video(
                    directory=td,
                    prompt="Test",
                    duration_seconds=15,
                    base_url="https://api.cometapi.com",
                    api_key="key",
                    fast_model="veo3.1-fast",
                    poll=AsyncMock(),
                    submit_initial=AsyncMock(),
                    extend_video=AsyncMock(side_effect=AssertionError("must not resubmit")),
                )
            self.assertEqual(result.name, "final_15s.mp4")

    async def test_confirmed_rejection_can_be_retried_without_resubmitting_initial_video(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            (directory / "scene_01.mp4").write_bytes(b"x" * 2048)
            write_job(directory / "journal.json", {
                "scenes": {"1": {"state": "completed", "task_id": "initial"}}
            })
            (directory / "extension_01.json").write_text(
                json.dumps({"status": "rejected", "step": 1}), encoding="utf-8"
            )
            extend = AsyncMock(return_value=b"y" * 2048)
            with patch(
                "neyrobot_prod.veo_extend_15_pipeline.probe_duration",
                side_effect=[15.0, 15.0, 15.0],
            ):
                await create_extended_video(
                    directory=td,
                    prompt="Test",
                    duration_seconds=15,
                    base_url="https://api.cometapi.com",
                    api_key="key",
                    fast_model="veo3.1-fast",
                    poll=AsyncMock(),
                    submit_initial=AsyncMock(side_effect=AssertionError("initial must not repeat")),
                    extend_video=extend,
                )
            extend.assert_awaited_once()

    async def test_duration_limit_is_checked_before_initial_submission(self):
        submit = AsyncMock()
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                await create_extended_video(
                    directory=td,
                    prompt="Test",
                    duration_seconds=149,
                    base_url="https://api.cometapi.com",
                    api_key="key",
                    fast_model="veo3.1-fast",
                    poll=AsyncMock(),
                    submit_initial=submit,
                )
        submit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
