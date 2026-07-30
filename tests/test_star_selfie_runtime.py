from pathlib import Path
import unittest

from neyrobot_prod.star_selfie.config import StarSelfieConfig
from neyrobot_prod.star_selfie.qc import BasicImageQC


class StarSelfieRuntimeTests(unittest.TestCase):
    def test_star_selfie_disabled_needs_no_secrets(self):
        config = StarSelfieConfig(project_root=Path("."), enabled=False, gemini_api_key="")
        config.validate_runtime()

    def test_star_selfie_enabled_requires_provider_settings(self):
        config = StarSelfieConfig(project_root=Path("."), enabled=True, gemini_api_key="")
        with self.assertRaises(RuntimeError) as exc:
            config.validate_runtime()
        self.assertIn("GEMINI_API_KEY", str(exc.exception))
        self.assertIn("STAR_SELFIE_FACE_SWAP_URL", str(exc.exception))

    def test_qc_rejects_provider_json_error(self):
        result = BasicImageQC().validate(b'{"error":"denied"}' + b" " * 20_000)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "non_image_payload")

    def test_qc_accepts_large_jpeg(self):
        result = BasicImageQC().validate(b"\xff\xd8\xff" + b"0" * 20_000)
        self.assertTrue(result.accepted)


if __name__ == "__main__":
    unittest.main()
