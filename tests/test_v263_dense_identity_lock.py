# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from neyrobot_prod import selfie_v263_dense_identity_lock as v263


class V263DenseIdentityLockTests(unittest.TestCase):
    def test_v263_loads_after_v262_and_becomes_successor(self) -> None:
        chain = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v262_landmark_field_compositor", chain)
        self.assertIn("_v247_base_overlay()", package)
        self.assertIn("selfie_v263_runtime_safety", package)
        self.assertIn("selfie_v263_dense_identity_lock", package)
        self.assertLess(package.index("_v247_base_overlay()"), package.index("_install_v263_identity()"))
        self.assertIn("AI_SELFIE_V263_INSTALL status=ok base=v262 rollback=v262", package)

    def test_v263_uses_mit_68_landmark_and_mobileface_models_without_new_opencv_dependency(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("_DENSE_COUNT = 68", source)
        self.assertIn("pipnet_r18_300w_celeba_68.onnx", source)
        self.assertIn("mobilenetv2.onnx", source)
        self.assertIn("pipnet_68_mit", source)
        self.assertIn("mobileface_v2_mit", source)
        self.assertIn("cv2.dnn.readNetFromONNX", source)
        self.assertIn("geometry_mode=pipnet_68", source)
        self.assertIn("landmarks=68", source)
        self.assertIn("opencv-python-headless==4.10.0.84", requirements)
        self.assertNotIn("mediapipe", requirements.lower())
        self.assertNotIn("opencv-contrib-python", requirements)
        self.assertIn("63fa56fd4b8f6ccc4b88f2b36e00fa3d8c21a2c4244ab9381e8b432cef35197b", source)
        self.assertIn("38b148284dd48cc898d5d4453104252fbdcbacc105fe3f0b80e78954d9d20d89", source)

    def test_inner_face_geometry_is_source_dominant_in_standard_and_strict(self) -> None:
        projected = np.zeros((68, 2), dtype=np.float32)
        target = np.full((68, 2), 100.0, dtype=np.float32)
        standard = v263._desired_identity_geometry(projected, target, 600.0, strict=False)
        strict = v263._desired_identity_geometry(projected, target, 600.0, strict=True)
        inner_idx = 39
        self.assertLess(float(standard[inner_idx, 0]), 20.0)
        self.assertLess(float(strict[inner_idx, 0]), float(standard[inner_idx, 0]))
        self.assertGreater(float(standard[0, 0]), float(standard[inner_idx, 0]))

    def test_quality_gate_accepts_good_and_rejects_identity_or_eye_failures(self) -> None:
        good = {
            "identity_similarity_cosine": 0.72,
            "left_eye_error": 0.025,
            "right_eye_error": 0.030,
            "interocular_ratio_delta": 0.020,
            "nose_mouth_axis_delta": 0.030,
            "inner_face_landmark_nme": 0.035,
            "eye_asymmetry_delta": 0.020,
        }
        ok, failures = v263._quality_gate(good)
        self.assertTrue(ok)
        self.assertEqual(failures, [])
        ok, failures = v263._quality_gate(dict(good, identity_similarity_cosine=0.20))
        self.assertFalse(ok)
        self.assertTrue(any("identity_similarity_cosine" in item for item in failures))
        ok, failures = v263._quality_gate(dict(good, left_eye_error=0.20))
        self.assertFalse(ok)
        self.assertTrue(any("left_eye_error" in item for item in failures))

    def test_required_identity_metrics_and_strict_retry_are_logged(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        for marker in (
            "identity_similarity_cosine", "left_eye_error", "right_eye_error",
            "interocular_ratio_delta", "nose_mouth_axis_delta", "inner_face_landmark_nme",
            "strict_retry_triggered", "strict_retry_success", "geometry_mode=pipnet_68", "landmarks=68",
        ):
            self.assertIn(marker, source)
        self.assertIn("AI_SELFIE_V263_STRICT_RETRY", source)
        self.assertIn("AI_SELFIE_V263_IDENTITY_REJECT", source)
        self.assertIn("raise RuntimeError(\"V263 identity quality gate rejected", source)

    def test_v263_preserves_v262_firewall_no_neck_and_document_delivery(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        self.assertIn("v262._landmark_anatomy_mask", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("person_b_untouched=true", source)
        self.assertIn("independent_eye_patch=false", source)
        self.assertIn("no_neck=true", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("AI_SELFIE_SEND_AS_DOCUMENT = True", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)
        self.assertNotIn("for eye_index in", source)

    def test_dense_quality_metrics_are_scale_normalized_and_eye_sensitive(self) -> None:
        desired = np.zeros((68, 2), dtype=np.float32)
        desired[list(v263._RIGHT_EYE)] = np.array([30.0, 40.0], dtype=np.float32)
        desired[list(v263._LEFT_EYE)] = np.array([70.0, 40.0], dtype=np.float32)
        desired[list(v263._NOSE)] = np.array([50.0, 60.0], dtype=np.float32)
        desired[list(v263._MOUTH)] = np.array([50.0, 80.0], dtype=np.float32)
        final = desired.copy()
        emb = np.zeros((512,), dtype=np.float32)
        emb[0] = 1.0
        good = v263._quality_metrics(emb, emb, desired, final)
        self.assertAlmostEqual(good["identity_similarity_cosine"], 1.0, places=6)
        self.assertAlmostEqual(good["left_eye_error"], 0.0, places=6)
        self.assertAlmostEqual(good["right_eye_error"], 0.0, places=6)
        shifted = final.copy()
        shifted[list(v263._LEFT_EYE), 0] += 8.0
        bad = v263._quality_metrics(emb, emb, desired, shifted)
        self.assertGreater(bad["left_eye_error"], good["left_eye_error"])
        self.assertGreater(bad["interocular_ratio_delta"], good["interocular_ratio_delta"])

    def test_v263_structure_first_and_no_raw_low_frequency_source_core(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        geometry_pos = source.index("_dense_deform_roi(")
        colour_pos = source.index("matched = v253._colour_match_lab")
        detail_pos = source.index("structure = fine_low - coarse_low")
        self.assertLess(geometry_pos, colour_pos)
        self.assertLess(colour_pos, detail_pos)
        self.assertIn("structure_first=true", source)
        self.assertIn("raw_low_frequency_reinject=false", source)
        self.assertIn("solid_source_core=false", source)

    def test_small_face_mask_guard_is_scale_normalized_without_relaxing_large_face_cap(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        self.assertIn("min(12000.0, max(3200.0, face_min * face_min * 0.30))", source)
        self.assertIn("if mask_pixels < min_mask_pixels:", source)
        self.assertIn("mask_min_pixels=%s", source)
        self.assertNotIn("if mask_pixels < 12000:", source)

    def test_startup_activation_has_explicit_v262_rollback_boundary(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("V247's original overlay first", source)
        self.assertIn('if not bool(getattr(_v262, "_INSTALLED", False))', source)
        self.assertIn("selfie_v263_runtime_safety", source)
        self.assertIn("_install_v263_runtime_safety()", source)
        self.assertIn("AI_SELFIE_V263_INSTALL status=ok base=v262 rollback=v262", source)
        self.assertIn("AI_SELFIE_V263_INSTALL status=failed rollback=v262", source)
        self.assertLess(source.index("_v247_base_overlay()"), source.index("_install_v263_runtime_safety()"))
        self.assertLess(source.index("_install_v263_runtime_safety()"), source.index("_install_v263_identity()"))

    def test_model_runtime_is_cached_thread_safe_and_process_safe(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_runtime_safety.py").read_text(encoding="utf-8")
        for marker in (
            "_VERIFIED_MODELS", "asyncio.Lock()", "threading.RLock()", "os.getpid()",
            ".replace(path)", "cache=verified", "process_safe=true", "_PIPNET_INFER_LOCK", "_MOBILEFACE_INFER_LOCK",
        ):
            self.assertIn(marker, source)
        self.assertIn("V263InfrastructureUnavailable", source)
        self.assertIn("fallback_v262", source)
        self.assertIn("identity_gate_bypass=false", source)
        self.assertIn("identity_reject_rollback=false", source)

    def test_quality_gate_normal_variation_matrix_avoids_mass_false_rejects(self) -> None:
        cases = {
            "frontal_male": (0.72, 0.025, 0.024, 0.018, 0.025, 0.032, 0.018),
            "slight_turn": (0.61, 0.052, 0.055, 0.045, 0.058, 0.064, 0.052),
            "frontal_female": (0.70, 0.030, 0.032, 0.022, 0.030, 0.038, 0.024),
            "small_face": (0.55, 0.065, 0.068, 0.058, 0.064, 0.072, 0.070),
            "two_person": (0.66, 0.038, 0.040, 0.030, 0.040, 0.048, 0.032),
            "complex_light": (0.54, 0.060, 0.062, 0.050, 0.060, 0.070, 0.064),
        }
        accepted = 0
        for label, values in cases.items():
            metrics = {
                "identity_similarity_cosine": values[0], "left_eye_error": values[1],
                "right_eye_error": values[2], "interocular_ratio_delta": values[3],
                "nose_mouth_axis_delta": values[4], "inner_face_landmark_nme": values[5],
                "eye_asymmetry_delta": values[6],
            }
            ok, failures = v263._quality_gate(metrics)
            self.assertTrue(ok, f"normal class {label} unexpectedly rejected: {failures}")
            accepted += int(ok)
        self.assertEqual(accepted, len(cases))

    def test_retry_contract_is_exactly_standard_then_one_strict_attempt(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        body = source[source.index("async def _true_face_transfer_v263"):source.index("def enforce_runtime")]
        self.assertEqual(body.count("_transfer_attempt("), 2)
        self.assertIn("strict=False", body)
        self.assertIn("strict=True", body)
        self.assertNotIn("while ", body)
        self.assertNotIn("for attempt", body)
        self.assertIn('raise RuntimeError("V263 identity quality gate rejected', body)

    def test_package_version_advances_to_v263_and_retains_v262_marker(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("v262-landmark-field-compositor-2026-08-27", source)
        self.assertIn('VERSION = "v263-dense-identity-lock-2026-08-27"', source)
        self.assertNotIn('VERSION = "v262-landmark-field-compositor-2026-08-27"', source)


if __name__ == "__main__":
    unittest.main()
