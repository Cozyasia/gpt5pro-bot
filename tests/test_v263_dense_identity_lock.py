# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import numpy as np

from neyrobot_prod import dense68_engine_v265 as engine
from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v265_single_owner as v265


class DenseIdentityProductionTests(unittest.TestCase):
    def test_v263_remains_dense68_model_math_utility_only(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_dense_identity_lock.py").read_text(encoding="utf-8")
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("_DENSE_COUNT = 68", source)
        self.assertIn("pipnet_r18_300w_celeba_68.onnx", source)
        self.assertIn("mobilenetv2.onnx", source)
        self.assertIn("cv2.dnn.readNetFromONNX", source)
        self.assertIn("landmarks=68", source)
        self.assertIn("opencv-python-headless==4.10.0.84", requirements)
        self.assertNotIn("mediapipe", requirements.lower())
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("selfie_v263_dense_identity_lock", package)

    def test_inner_face_geometry_math_remains_source_dominant(self) -> None:
        projected = np.zeros((68, 2), dtype=np.float32)
        target = np.full((68, 2), 100.0, dtype=np.float32)
        standard = v263._desired_identity_geometry(projected, target, 600.0, strict=False)
        strict = v263._desired_identity_geometry(projected, target, 600.0, strict=True)
        inner_idx = 39
        self.assertLess(float(standard[inner_idx, 0]), 20.0)
        self.assertLess(float(strict[inner_idx, 0]), float(standard[inner_idx, 0]))
        self.assertGreater(float(standard[0, 0]), float(standard[inner_idx, 0]))

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

    def test_v265_heavy_processing_is_roi_only_and_dense68(self) -> None:
        source = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        body = source[source.index("def transfer_attempt"):source.index("def _match_eye_luminance")]
        self.assertIn("target_roi = target[y0:y1, x0:x1].copy()", body)
        self.assertIn("mask_roi = anatomy_mask[y0:y1, x0:x1].copy()", body)
        self.assertIn("_warp_source_direct_to_roi(source_im, matrix", body)
        self.assertIn("_dense_deform_local_roi(", body)
        self.assertIn("_structure_first_compose_roi(", body)
        self.assertIn("for idx in range(v263._DENSE_COUNT):", source)
        self.assertIn('"source_photo3_v265"', body)
        self.assertIn('"target_person_a_v265"', body)
        self.assertIn("source_dense = v263._dense_landmarks_68", body)
        self.assertIn("target_dense = v263._dense_landmarks_68", body)
        self.assertIn("landmarks=68", body)
        self.assertIn("roi_only=true", body)
        self.assertNotIn("cv2.warpAffine(source_im, matrix, (tw, th)", body)

    def test_v265_preserves_person_b_no_neck_and_lossless_png(self) -> None:
        engine_source = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        owner = Path("neyrobot_prod/selfie_v265_single_owner.py").read_text(encoding="utf-8")
        self.assertIn("def _landmark_anatomy_mask", engine_source)
        self.assertIn("Inner-face anatomical hull. No ellipse, neck, hair or full-head source mask.", engine_source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", engine_source)
        self.assertIn("person_b=pixel_locked", engine_source)
        self.assertIn('cv2.imencode(".png"', engine_source)
        self.assertIn("reply_document", owner)
        self.assertNotIn("reply_photo", inspect.getsource(v265._deliver_original_only))

    def test_v265_asymmetry_is_refinement_signal_not_hard_reject(self) -> None:
        metrics = {
            "identity_similarity_cosine": 0.7609,
            "left_eye_error": 0.0102,
            "right_eye_error": 0.0297,
            "interocular_ratio_delta": 0.0256,
            "nose_mouth_axis_delta": 0.0215,
            "inner_face_landmark_nme": 0.0273,
            "eye_asymmetry_delta": 0.0585,
            "target_face_short": 571.0,
        }
        passed, failures = v265.production_gate(metrics)
        self.assertTrue(passed, failures)
        reasons = engine.visual_refinement_reasons(metrics)
        self.assertTrue(any(item.startswith("eye_asymmetry=") for item in reasons))

    def test_v265_rejects_real_single_eye_deformation(self) -> None:
        metrics = {
            "identity_similarity_cosine": 0.82,
            "left_eye_error": 0.018,
            "right_eye_error": 0.090,
            "interocular_ratio_delta": 0.025,
            "nose_mouth_axis_delta": 0.022,
            "inner_face_landmark_nme": 0.030,
            "eye_asymmetry_delta": 0.072,
            "target_face_short": 600.0,
        }
        passed, failures = v265.production_gate(metrics)
        self.assertFalse(passed)
        self.assertTrue(any("eye_error=" in item for item in failures))

    def test_v265_retry_is_exactly_standard_then_one_strict_same_engine(self) -> None:
        body = inspect.getsource(v265._true_face_transfer_v265)
        self.assertEqual(body.count("engine.transfer_attempt("), 2)
        self.assertEqual(body.count("engine.apply_ocular_lock("), 2)
        self.assertIn("strict=False", body)
        self.assertIn("strict=True", body)
        self.assertNotIn("while ", body)
        self.assertNotIn("for attempt", body)
        for forbidden in (
            "_true_face_transfer_v262", "selfie_v264_", "_provider_rescue(", "segmind", "piapi"
        ):
            self.assertNotIn(forbidden, body.lower() if forbidden in ("segmind", "piapi") else body)

    def test_runtime_safety_remains_cached_and_process_safe(self) -> None:
        source = Path("neyrobot_prod/selfie_v263_runtime_safety.py").read_text(encoding="utf-8")
        for marker in (
            "_VERIFIED_MODELS", "asyncio.Lock()", "threading.RLock()", "os.getpid()",
            ".replace(path)", "cache=verified", "process_safe=true", "_PIPNET_INFER_LOCK", "_MOBILEFACE_INFER_LOCK",
        ):
            self.assertIn(marker, source)

    def test_package_and_version_report_v265_single_owner(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v265-dense68-single-owner-production-2026-09-01"', package)
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertIn("V263_PRODUCTION_ACCEPTED = False", package)
        self.assertIn("V264_PRODUCTION_ACCEPTED = False", package)
        self.assertIn("V265_PRODUCTION_ACCEPTED = True", package)
        self.assertIn("_install_v265_from_v246_entrypoint", package)
        self.assertNotIn("selfie_v264_dense68_roi_production", package)
        versioning = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('active == "v265"', versioning)
        self.assertIn("selfie_v265_single_owner", versioning)
        self.assertIn("68-point", versioning)

    def test_normal_variation_quality_matrix_remains_accepted_by_v265(self) -> None:
        cases = {
            "frontal_male": (0.72, 0.025, 0.024, 0.018, 0.025, 0.032, 0.018, 600.0),
            "frontal_female": (0.70, 0.030, 0.032, 0.022, 0.030, 0.038, 0.024, 600.0),
            "two_person": (0.66, 0.038, 0.040, 0.030, 0.040, 0.048, 0.032, 420.0),
            "small_face": (0.60, 0.065, 0.068, 0.058, 0.064, 0.069, 0.070, 300.0),
        }
        for label, values in cases.items():
            metrics = {
                "identity_similarity_cosine": values[0], "left_eye_error": values[1],
                "right_eye_error": values[2], "interocular_ratio_delta": values[3],
                "nose_mouth_axis_delta": values[4], "inner_face_landmark_nme": values[5],
                "eye_asymmetry_delta": values[6], "target_face_short": values[7],
            }
            ok, failures = v265.production_gate(metrics)
            self.assertTrue(ok, f"normal class {label} unexpectedly rejected: {failures}")


if __name__ == "__main__":
    unittest.main()
