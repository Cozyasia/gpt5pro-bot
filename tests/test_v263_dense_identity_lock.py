# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v264_dense68_roi_production as v264


class DenseIdentityProductionTests(unittest.TestCase):
    def test_v263_still_supplies_dense68_identity_geometry_and_models(self) -> None:
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

    def test_inner_face_geometry_remains_source_dominant(self) -> None:
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
        shifted = final.copy()
        shifted[list(v263._LEFT_EYE), 0] += 8.0
        bad = v263._quality_metrics(emb, emb, desired, shifted)
        self.assertGreater(bad["left_eye_error"], good["left_eye_error"])
        self.assertGreater(bad["interocular_ratio_delta"], good["interocular_ratio_delta"])

    def test_v264_heavy_processing_is_roi_only(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        body = source[source.index("def _transfer_attempt_roi"):source.index("async def _true_face_transfer_v264")]
        self.assertIn("target_roi = target[y0:y1, x0:x1].copy()", body)
        self.assertIn("mask_roi = anatomy_mask[y0:y1, x0:x1].copy()", body)
        self.assertIn("_warp_source_direct_to_roi(source_im, matrix, box)", body)
        self.assertIn("_dense_deform_local_roi(", body)
        self.assertIn("_structure_first_compose_roi(", body)
        self.assertNotIn("cv2.warpAffine(source_im, matrix, (tw, th)", body)
        self.assertNotIn("v253._colour_match_lab", source)
        self.assertIn("roi_only=true", source)
        self.assertIn("full_frame_source_warp=false", source)
        self.assertIn("full_frame_float=false", source)
        self.assertIn("colour_match=lab_roi_only", source)

    def test_v264_dense_field_uses_all_68_points_in_local_coordinates(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        body = source[source.index("def _dense_deform_local_roi"):source.index("def _structure_first_compose_roi")]
        self.assertIn("for idx in range(v263._DENSE_COUNT):", body)
        self.assertIn("np.asarray([float(x0), float(y0)]", body)
        self.assertIn("np.zeros((roi_h, roi_w), dtype=np.float32)", body)
        self.assertIn("cv2.remap(", body)
        self.assertNotIn("for eye_index in", body)

    def test_v264_keeps_yunet_five_points_only_for_global_pose(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        body = source[source.index("def _transfer_attempt_roi"):source.index("async def _true_face_transfer_v264")]
        self.assertIn("source_pts5", body)
        self.assertIn("target_pts5", body)
        self.assertIn("v263._similarity_transform(source_pts5, target_pts5)", body)
        self.assertIn("source_dense = v263._dense_landmarks_68", body)
        self.assertIn("target_dense = v263._dense_landmarks_68", body)
        self.assertIn("v263._desired_identity_geometry(projected_dense, target_dense", body)

    def test_v264_preserves_person_b_no_neck_and_lossless_document(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        self.assertIn("v262._landmark_anatomy_mask", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("person_b_untouched=true", source)
        self.assertIn("independent_eye_patch=false", source)
        self.assertIn("no_neck=true", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("AI_SELFIE_SEND_AS_DOCUMENT = True", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_v264_retry_is_exactly_standard_then_one_strict_attempt(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        body = source[source.index("async def _true_face_transfer_v264"):source.index("def enforce_runtime")]
        self.assertEqual(body.count("_transfer_attempt_roi("), 2)
        self.assertIn("strict=False", body)
        self.assertIn("strict=True", body)
        self.assertNotIn("while ", body)
        self.assertNotIn("for attempt", body)
        self.assertIn("AI_SELFIE_V264_IDENTITY_REJECT", body)

    def test_only_infrastructure_failure_may_fall_back_to_v262(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        body = source[source.index("async def _true_face_transfer_v264"):source.index("def enforce_runtime")]
        self.assertIn("V263InfrastructureUnavailable", body)
        self.assertIn("AI_SELFIE_V264_INFRA_FALLBACK", body)
        self.assertIn("identity_gate_bypass=false", body)
        self.assertIn("v262._true_face_transfer_v262", body)
        self.assertIn("raise\n", body)

    def test_runtime_safety_remains_cached_and_process_safe(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_runtime_safety.py").read_text(encoding="utf-8")
        for marker in (
            "_VERIFIED_MODELS", "asyncio.Lock()", "threading.RLock()", "os.getpid()",
            ".replace(path)", "cache=verified", "process_safe=true", "_PIPNET_INFER_LOCK", "_MOBILEFACE_INFER_LOCK",
        ):
            self.assertIn(marker, source)

    def test_package_installs_v264_after_v262_and_dense_model_safety(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v264-dense68-roi-production-2026-08-31"', package)
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v264"', package)
        self.assertIn("V263_PRODUCTION_ACCEPTED = False", package)
        self.assertIn("V264_PRODUCTION_ACCEPTED = True", package)
        self.assertIn("selfie_v263_runtime_safety", package)
        self.assertIn("selfie_v264_dense68_roi_production", package)
        self.assertLess(package.index("_v247_base_overlay()"), package.index("_install_v263_runtime_safety()"))
        self.assertLess(package.index("_install_v263_runtime_safety()"), package.index("_install_v264_identity()"))
        self.assertIn("AI_SELFIE_V264_INSTALL status=ok", package)
        self.assertIn("AI_SELFIE_V264_INSTALL status=failed rollback=v262", package)

    def test_version_command_reports_and_reasserts_v264(self) -> None:
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn("PRODUCTION_SELFIE_RUNTIME", source)
        self.assertIn('if active == "v264"', source)
        self.assertIn("selfie_v264_dense68_roi_production import install", source)
        self.assertIn("68-point dense identity · ROI-only production", source)
        self.assertIn("V262: только аварийный fallback", source)

    def test_normal_variation_quality_matrix_remains_accepted(self) -> None:
        cases = {
            "frontal_male": (0.72, 0.025, 0.024, 0.018, 0.025, 0.032, 0.018),
            "slight_turn": (0.61, 0.052, 0.055, 0.045, 0.058, 0.064, 0.052),
            "frontal_female": (0.70, 0.030, 0.032, 0.022, 0.030, 0.038, 0.024),
            "small_face": (0.55, 0.065, 0.068, 0.058, 0.064, 0.072, 0.070),
            "two_person": (0.66, 0.038, 0.040, 0.030, 0.040, 0.048, 0.032),
            "complex_light": (0.54, 0.060, 0.062, 0.050, 0.060, 0.070, 0.064),
        }
        for label, values in cases.items():
            metrics = {
                "identity_similarity_cosine": values[0], "left_eye_error": values[1],
                "right_eye_error": values[2], "interocular_ratio_delta": values[3],
                "nose_mouth_axis_delta": values[4], "inner_face_landmark_nme": values[5],
                "eye_asymmetry_delta": values[6],
            }
            ok, failures = v263._quality_gate(metrics)
            self.assertTrue(ok, f"normal class {label} unexpectedly rejected: {failures}")


if __name__ == "__main__":
    unittest.main()
