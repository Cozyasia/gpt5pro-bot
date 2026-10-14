import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neyrobot_prod.veo_start_guard import begin_veo_job, end_veo_job, is_veo_job_active


class VeoStartGuardTests(unittest.TestCase):
    def test_docker_applies_start_guard_after_veo_production_patch(self):
        dockerfile = Path(__file__).parents[1].joinpath("Dockerfile").read_text(encoding="utf-8")
        self.assertIn("main_veo.patch", dockerfile)
        self.assertIn("main_veo_start_guard.patch", dockerfile)
        self.assertLess(dockerfile.index("main_veo.patch"), dockerfile.index("main_veo_start_guard.patch"))

    def test_active_veo_job_suppresses_start_until_finished(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ, {"VEO_JOBS_DIR": td}, clear=False
        ):
            self.assertTrue(begin_veo_job(7753015434, 7753015434, "job-1"))
            self.assertTrue(is_veo_job_active(7753015434, 7753015434))
            self.assertFalse(begin_veo_job(7753015434, 7753015434, "job-2"))
            end_veo_job(7753015434, 7753015434, "job-1")
            self.assertFalse(is_veo_job_active(7753015434, 7753015434))

    def test_stale_marker_is_removed_without_blocking_new_job(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ, {"VEO_JOBS_DIR": td}, clear=False
        ):
            marker = Path(td) / ".active_veo_1_2.json"
            marker.write_text('{"started_at": 1}', encoding="utf-8")
            with patch("neyrobot_prod.veo_start_guard.time.time", return_value=100_000):
                self.assertFalse(is_veo_job_active(1, 2))
                self.assertTrue(begin_veo_job(1, 2, "fresh"))


if __name__ == "__main__":
    unittest.main()
