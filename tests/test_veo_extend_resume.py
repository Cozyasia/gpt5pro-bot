import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from neyrobot_prod.veo_extend_15_pipeline import (
    ResumeRequired,
    create_extended_video,
)
from neyrobot_prod.veo_google_adapter import GoogleVeoOperationFailed


class VeoExtendResumeTests(unittest.TestCase):
    def test_failed_extend_is_retried_only_by_explicit_resume(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            initial_calls = []
            extension_calls = []
            first_attempt = True

            async def submit_initial():
                initial_calls.append("initial")
                return "initial-operation"

            async def poll(task_id):
                return (task_id + "-video").encode() * 256

            async def extend(source, prompt):
                nonlocal first_attempt
                extension_calls.append((source, prompt))
                if first_attempt and len(extension_calls) == 3:
                    first_attempt = False
                    raise GoogleVeoOperationFailed(
                        "Google Veo operation failed: {'code': 14, 'message': 'high demand'}"
                    )
                return b"cumulative-video" * 256

            def duration(path):
                name = Path(path).name
                if name == "scene_01.mp4":
                    return 8.0
                if name.startswith("extension_"):
                    return 8.0 + 7.0 * int(name[10:12])
                if name.startswith("final_"):
                    return 30.0
                raise AssertionError(f"unexpected probe path: {path}")

            async def run():
                with patch(
                    "neyrobot_prod.veo_extend_15_pipeline.probe_duration",
                    side_effect=duration,
                ), patch(
                    "subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stderr=b""),
                ):
                    with self.assertRaises(GoogleVeoOperationFailed):
                        await create_extended_video(
                            directory=directory,
                            prompt="test prompt",
                            duration_seconds=30,
                            base_url="https://unused",
                            api_key="unused",
                            fast_model="unused",
                            poll=poll,
                            submit_initial=submit_initial,
                            extend_video=extend,
                        )

                    state = json.loads((directory / "extension_03.json").read_text())
                    self.assertEqual(state["status"], "resume_required")

                    with self.assertRaises(ResumeRequired):
                        await create_extended_video(
                            directory=directory,
                            prompt="test prompt",
                            duration_seconds=30,
                            base_url="https://unused",
                            api_key="unused",
                            fast_model="unused",
                            poll=poll,
                            submit_initial=submit_initial,
                            extend_video=extend,
                        )

                    result = await create_extended_video(
                        directory=directory,
                        prompt="test prompt",
                        duration_seconds=30,
                        base_url="https://unused",
                        api_key="unused",
                        fast_model="unused",
                        poll=poll,
                        submit_initial=submit_initial,
                        extend_video=extend,
                        resume_only=True,
                    )
                    return result

            result = asyncio.run(run())
            self.assertEqual(result, directory / "final_30s.mp4")
            self.assertEqual(initial_calls, ["initial"])
            self.assertEqual(len(extension_calls), 5)
            self.assertEqual(
                [Path(source).name if isinstance(source, (str, Path)) else type(source).__name__
                 for source, _ in extension_calls],
                ["bytes", "bytes", "bytes", "bytes", "bytes"],
            )
            self.assertEqual(
                json.loads((directory / "extension_01.json").read_text())["status"],
                "accepted",
            )


if __name__ == "__main__":
    unittest.main()
