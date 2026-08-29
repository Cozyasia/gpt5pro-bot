# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neyrobot_prod import v263_validation_sentinel as sentinel


class V263RuntimeCrashInvestigationTests(unittest.TestCase):
    def test_granular_native_crash_checkpoints_are_present(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        for marker in (
            "pipnet_source.before", "pipnet_source.after",
            "pipnet_target.before", "pipnet_target.after",
            "dense_field.before", "dense_field.after",
            "warp_affine.before", "warp_affine.after",
            "remap.before", "remap.after",
            "anatomical_mask.before", "anatomical_mask.after",
            "structure_first_compositor.before", "structure_first_compositor.after",
            "mobileface_source.before", "mobileface_source.after",
            "mobileface_final.before", "mobileface_final.after",
            "metrics.before", "metrics.after",
            "standard_quality_gate.before", "standard_quality_gate.after",
            "strict_retry.before", "strict_retry.after",
        ):
            self.assertIn(marker, source)

    def test_diagnostics_are_metadata_only_and_report_rss_peak_and_buffers(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_diagnostics.py").read_text(encoding="utf-8")
        for marker in ("VmRSS:", "VmHWM:", "ru_maxrss", "approx_buffer_bytes", "rss_bytes", "peak_rss_bytes", "elapsed_ms"):
            self.assertIn(marker, source)
        self.assertNotIn("tobytes()", source)
        self.assertNotIn("base64", source.lower())

    def test_quality_thresholds_and_dense_geometry_are_not_relaxed(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        # Freeze the exact investigation-branch gate/geometry values. Instrumentation
        # must not move these numbers merely to obtain an output image.
        expected = (
            "_IDENTITY_COSINE_MIN = 0.50",
            "_INNER_FACE_NME_MAX = 0.080",
            "_EYE_ERROR_MAX = 0.075",
            "_INTEROCULAR_RATIO_DELTA_MAX = 0.065",
            "_NOSE_MOUTH_AXIS_DELTA_MAX = 0.075",
            "_EYE_ASYMMETRY_MAX = 0.085",
            "_DENSE_COUNT = 68",
            "_STANDARD_MAX_SHIFT_FRACTION = 0.055",
            "_STRICT_MAX_SHIFT_FRACTION = 0.028",
        )
        for marker in expected:
            self.assertIn(marker, source)

    def test_production_size_fixture_matches_failed_load_class(self) -> None:
        source = Path("scripts/v263_production_size_fixture.py").read_text(encoding="utf-8")
        self.assertIn("WIDTH = 1856", source)
        self.assertIn("HEIGHT = 2304", source)
        self.assertIn("person_b_untouched", source)
        self.assertIn("quality_gate_reached", source)
        self.assertIn("peak_delta_bytes", source)

    def test_sentinel_started_state_blocks_repeat_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "v263-validation.json"
            self.assertTrue(sentinel.arm(path, run_id="diagnostic-1"))
            self.assertEqual(sentinel.read_state(path)["state"], "armed")
            self.assertTrue(sentinel.mark_started(path, run_id="diagnostic-1"))
            self.assertEqual(sentinel.read_state(path)["state"], "started")
            # Simulated process restart: the next startup must not re-arm or re-run.
            self.assertFalse(sentinel.arm(path, run_id="diagnostic-1"))
            self.assertFalse(sentinel.mark_started(path, run_id="diagnostic-1"))
            self.assertEqual(sentinel.read_state(path)["state"], "started")
            sentinel.mark_completed(path, run_id="diagnostic-1")
            self.assertEqual(sentinel.read_state(path)["state"], "completed")


if __name__ == "__main__":
    unittest.main()
