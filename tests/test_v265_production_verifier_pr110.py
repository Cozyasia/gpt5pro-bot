# -*- coding: utf-8 -*-
import inspect
import unittest


class V265ProductionVerifierPR110Tests(unittest.TestCase):
    def test_verifier_is_one_shot_observer_only(self):
        from neyrobot_prod import v265_production_verifier as verifier

        source = inspect.getsource(verifier)
        self.assertIn("v265_prod_verify_pr110_stability_quality_v1.once", source)
        self.assertIn("os.O_EXCL", source)
        self.assertIn("heavy_started_after_sentinel=true", source)
        self.assertIn("base_ocular = engine.apply_ocular_lock", source)
        self.assertIn("return result, metrics", source)
        self.assertNotIn("V262", source)
        self.assertNotIn("Segmind", source)
        self.assertNotIn("PiAPI", source)
        self.assertNotIn("_LARGE_IDENTITY_MIN", source)

    def test_quality_failure_keeps_second_candidate_without_third_attempt(self):
        from neyrobot_prod import v265_production_verifier as verifier

        source = inspect.getsource(verifier._verify_async)
        self.assertEqual(source.count("_true_face_transfer_v265("), 1)
        self.assertIn("diagnostic_final, diagnostic_metrics = captured[-1]", source)
        self.assertIn("strict_observed", source)


if __name__ == "__main__":
    unittest.main()
