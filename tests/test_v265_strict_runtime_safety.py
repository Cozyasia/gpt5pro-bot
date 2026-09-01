# -*- coding: utf-8 -*-
import unittest


class V265StrictRuntimeSafetyTests(unittest.TestCase):
    def test_strict_runs_only_after_preflight_without_changing_gate(self):
        from neyrobot_prod import dense68_engine_v265 as engine
        from neyrobot_prod import selfie_v265_single_owner as v265
        import neyrobot_prod.v265_strict_runtime_safety as safety

        base_gate = v265.production_gate
        base_transfer = engine.transfer_attempt
        base_preflight = safety._strict_preflight
        calls = []
        preflights = []

        def fake_transfer(*args, strict=False, **kwargs):
            calls.append(bool(strict))
            return b"candidate", {"target_face_short": 600.0}, object()

        def fake_preflight():
            preflights.append(True)

        engine.transfer_attempt = fake_transfer
        safety._strict_preflight = fake_preflight
        safety._INSTALLED = False
        safety._BASE_TRANSFER = None
        safety.install()
        try:
            engine.transfer_attempt(b"stage1", b"source", None, None, None, strict=False)
            self.assertEqual(calls, [False])
            self.assertEqual(preflights, [])
            engine.transfer_attempt(b"stage1", b"source", None, None, None, strict=True)
            self.assertEqual(calls, [False, True])
            self.assertEqual(preflights, [True])
            self.assertIs(v265.production_gate, base_gate)
        finally:
            engine.transfer_attempt = base_transfer
            safety._strict_preflight = base_preflight
            safety._INSTALLED = False
            safety._BASE_TRANSFER = None

    def test_low_headroom_fails_closed_before_strict(self):
        import neyrobot_prod.v265_strict_runtime_safety as safety

        base_reclaim = safety._reclaim_before_strict
        safety._reclaim_before_strict = lambda: (500 * 1024 * 1024, 512 * 1024 * 1024, 480 * 1024 * 1024)
        try:
            with self.assertRaisesRegex(RuntimeError, "insufficient container memory headroom"):
                safety._strict_preflight()
        finally:
            safety._reclaim_before_strict = base_reclaim


if __name__ == "__main__":
    unittest.main()
