# -*- coding: utf-8 -*-
from pathlib import Path
import unittest

import celebrity_selfie_v132_guard as guard


class CelebritySelfieV132GuardTests(unittest.TestCase):
    def test_current_selection_must_match_job_snapshot(self):
        session = {
            "generation_id": "job-1",
            "scene": "Красная площадь",
            "celebrity_name": "Роман Абрамович",
            "generation_scene_snapshot": "Красная площадь",
            "generation_celebrity_snapshot": "Роман Абрамович",
        }
        self.assertTrue(
            guard._same_job_selection(
                session, "job-1", "Красная площадь", "Роман Абрамович"
            )
        )
        session["scene"] = "Яхта"
        self.assertFalse(
            guard._same_job_selection(
                session, "job-1", "Красная площадь", "Роман Абрамович"
            )
        )

    def test_provider_details_are_replaced_with_public_failure_reason(self):
        reason = guard._public_failure(
            RuntimeError("PiAPI task 123 failed with private upstream payload")
        )
        self.assertEqual(reason, "не удалось надёжно закрепить оба лица")
        self.assertNotIn("123", reason)

    def test_v132_guard_is_reused_internally_but_only_v133_builder_is_bootstrapped(self):
        bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        release = Path("celebrity_selfie_v133.py").read_text(encoding="utf-8")
        self.assertNotIn("from celebrity_selfie_v132_guard import install", bootstrap)
        self.assertNotIn("from celebrity_selfie_v132 import install_builder_hook", bootstrap)
        self.assertIn("from celebrity_selfie_v133 import install_builder_hook", bootstrap)
        self.assertIn("import celebrity_selfie_v132_guard as base_guard", release)
        self.assertIn("base_guard._same_job_selection", release)


if __name__ == "__main__":
    unittest.main()
