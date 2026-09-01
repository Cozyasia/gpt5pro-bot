# -*- coding: utf-8 -*-
import inspect
import unittest


class V265VerifierReadinessTests(unittest.TestCase):
    def test_verifier_does_not_mutate_v265_runtime(self):
        import neyrobot_prod.v265_production_verifier as verifier
        source = inspect.getsource(verifier)
        self.assertNotIn("v265.production_gate =", source)
        self.assertNotIn("v265._true_face_transfer_v265 =", source)
        self.assertNotIn("transfer._true_face_transfer =", source)
        self.assertIn("_save_artifact(\"01_source_person_a.jpg\"", source)
        self.assertIn("_save_artifact(\"03_stage1_production_size.png\"", source)
        self.assertIn("_save_artifact(\"04_final_v265.png\"", source)
        self.assertIn("independent_eye_patch", source)
        self.assertIn("v263_quality_gate", source)

    def test_runtime_ready_wrapper_uses_actual_production_state(self):
        import neyrobot_prod.v265_production_verifier_runtime_ready as wrapper
        source = inspect.getsource(wrapper)
        self.assertNotIn("v265.production_gate =", source)
        self.assertNotIn("transfer._true_face_transfer =", source)
        self.assertIn("_claim_pending()", source)
        self.assertIn('"status": "pending"', source)
        self.assertIn('"status": "started"', source)
        self.assertIn("process_started", source)
        self.assertIn("bootstrap_v265", source)
        self.assertIn("owner_registered", source)
        self.assertIn("delivery_owner_registered", source)
        self.assertIn("dense68_available", source)
        self.assertIn("gemini_configured", source)
        self.assertIn("legacy_runtime_marker_matches_v265", source)
        self.assertIn("legacy_runtime_route_matches_v265", source)
        safe_block = source.split('checks["safe_to_begin"] = all(', 1)[1].split('details = {', 1)[0]
        self.assertNotIn("legacy_runtime_marker_matches_v265", safe_block)
        self.assertNotIn("legacy_runtime_route_matches_v265", safe_block)
        self.assertIn("base._SENTINEL = _SENTINEL", source)
        self.assertIn("base._ARTIFACT_DIR = _ARTIFACT_DIR", source)
        self.assertIn("127.0.0.1", source)


if __name__ == "__main__":
    unittest.main()
