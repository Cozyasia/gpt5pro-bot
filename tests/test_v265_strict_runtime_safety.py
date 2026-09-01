# -*- coding: utf-8 -*-
import unittest


class V265StrictRuntimeSafetyTests(unittest.TestCase):
    def test_strict_is_blocked_without_changing_standard_or_gate(self):
        from neyrobot_prod import dense68_engine_v265 as engine
        from neyrobot_prod import selfie_v265_single_owner as v265
        import neyrobot_prod.v265_strict_runtime_safety as safety

        base_gate = v265.production_gate
        base_transfer = engine.transfer_attempt
        calls = []

        def fake_transfer(*args, strict=False, **kwargs):
            calls.append(bool(strict))
            return b"standard", {"target_face_short": 600.0}, object()

        engine.transfer_attempt = fake_transfer
        safety._INSTALLED = False
        safety._BASE_TRANSFER = None
        safety._BASE_REFINEMENT_REASONS = None
        safety.install()
        try:
            out = engine.transfer_attempt(b"stage1", b"source", None, None, None, strict=False)
            self.assertEqual(out[0], b"standard")
            self.assertEqual(calls, [False])
            self.assertEqual(engine.visual_refinement_reasons({"target_face_short": 700.0}), [])
            with self.assertRaisesRegex(RuntimeError, "strict retry temporarily disabled"):
                engine.transfer_attempt(b"stage1", b"source", None, None, None, strict=True)
            self.assertIs(v265.production_gate, base_gate)
        finally:
            engine.transfer_attempt = base_transfer
            if safety._BASE_REFINEMENT_REASONS is not None:
                engine.visual_refinement_reasons = safety._BASE_REFINEMENT_REASONS
            safety._INSTALLED = False
            safety._BASE_TRANSFER = None
            safety._BASE_REFINEMENT_REASONS = None


if __name__ == "__main__":
    unittest.main()
