import json
import tempfile
import unittest
from pathlib import Path

from neyrobot_prod.veo_recovery import (
    callback_data,
    completed_extension_seconds,
    parse_callback_data,
    read_metadata,
    retryable_extension,
    write_metadata,
)


class VeoRecoveryTests(unittest.TestCase):
    def test_callback_data_is_bounded_to_a_valid_job_id(self):
        self.assertEqual(callback_data("a" * 24), "veoresume:" + "a" * 24)
        self.assertEqual(parse_callback_data("veoresume:" + "a" * 24), "a" * 24)
        self.assertIsNone(parse_callback_data("veoresume:not-a-job"))
        with self.assertRaises(ValueError):
            callback_data("../other-job")

    def test_retryable_checkpoint_and_owner_metadata_survive_restart(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            write_metadata(directory, owner_user_id=42, owner_chat_id=84, duration_seconds=30)
            (directory / "extension_01.json").write_text(json.dumps({
                "status": "accepted", "step": 1,
            }))
            (directory / "extension_02.json").write_text(json.dumps({
                "status": "accepted", "step": 2,
            }))
            (directory / "extension_03.json").write_text(json.dumps({
                "status": "resume_required", "retryable": True, "step": 3,
            }))
            self.assertEqual(read_metadata(directory)["owner_user_id"], 42)
            self.assertEqual(retryable_extension(directory)["step"], 3)
            self.assertEqual(completed_extension_seconds(directory), 22)


if __name__ == "__main__":
    unittest.main()
