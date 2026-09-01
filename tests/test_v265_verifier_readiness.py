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
        self.assertIn("_claim_pending()", source)
        self.assertIn('"status": "pending"', source)
        self.assertIn('"status": "started"', source)
        self.assertIn('"status": "completed"', source)
        self.assertIn("safe_to_begin", source)
        self.assertIn("dense68_available", source)
        self.assertIn("owner_registered", source)
        self.assertIn("runtime_contract", source)
        self.assertIn("_save_artifact(\"01_source_person_a.jpg\"", source)
        self.assertIn("_save_artifact(\"03_stage1_production_size.png\"", source)
        self.assertIn("_save_artifact(\"04_final_v265.png\"", source)
        self.assertIn("independent_eye_patch", source)
        self.assertIn("v263_quality_gate", source)


if __name__ == "__main__":
    unittest.main()
