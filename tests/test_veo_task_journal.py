import tempfile
import unittest
from pathlib import Path
from neyrobot_prod.veo_task_journal import mark_scene, may_submit, read_job


class JournalTests(unittest.TestCase):
    def test_prevents_duplicate_submission(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "job.json"
            self.assertTrue(may_submit(path, 1))
            mark_scene(path, 1, "submitting")
            self.assertFalse(may_submit(path, 1))
            mark_scene(path, 1, "accepted", "provider-123")
            self.assertFalse(may_submit(path, 1))
            self.assertEqual(read_job(path)["scenes"]["1"]["task_id"], "provider-123")

    def test_rejects_provider_id_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "job.json"
            mark_scene(path, 1, "accepted", "provider-123")
            with self.assertRaises(ValueError):
                mark_scene(path, 1, "accepted", "provider-456")

    def test_accepted_requires_id(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                mark_scene(Path(td) / "job.json", 1, "accepted")

if __name__ == "__main__":
    unittest.main()
