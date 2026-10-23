import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from property_video_billing import record_operation, reserve, status
from property_video_execution import recover_after_restart


class PropertyVideoRecoveryTests(unittest.TestCase):
    def test_restart_recovers_saved_scenes_without_provider_retry(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "subs.db")
            root = Path(td) / "jobs"
            job = "recover-job"
            folder = root / job
            folder.mkdir(parents=True)
            metadata = {"chat_id": 123, "user_id": 123, "engine": "kling", "duration": 20, "scene_count": 2}
            reserve(db, job, 123, 0, provider_cost_usd=3.2, metadata=metadata, owner_bypass=True)
            record_operation(db, job, "kling-1", provider="kling", scene_index=0)
            record_operation(db, job, "kling-2", provider="kling", scene_index=1)
            (folder / "scene_00.mp4").write_bytes(b"scene-1")
            (folder / "scene_01.mp4").write_bytes(b"scene-2")

            sent = SimpleNamespace(video=SimpleNamespace(file_id="telegram-file-1"))
            bot = SimpleNamespace(send_video=AsyncMock(return_value=sent))
            app = SimpleNamespace(bot=bot)

            def fake_assemble(paths, output, duration):
                Path(output).write_bytes(b"final-mp4")
                return output

            with patch.dict(os.environ, {"DB_PATH": db, "PROPERTY_VIDEO_ROOT": str(root)}, clear=False), \
                 patch("property_video_execution.assemble_property_video", side_effect=fake_assemble):
                asyncio.run(recover_after_restart(app))

            self.assertEqual(status(db, job)[0], "delivered")
            self.assertTrue((folder / "property_review.mp4").is_file())
            bot.send_video.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
