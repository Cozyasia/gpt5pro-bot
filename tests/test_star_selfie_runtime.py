from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from neyrobot_prod.star_selfie.config import StarSelfieConfig
from neyrobot_prod.star_selfie.diagnostics import build_report
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

    def test_diagnostics_do_not_expose_secrets_and_report_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.json"
            seed.write_text(json.dumps({"schema_version": 1, "characters": {}}), encoding="utf-8")
            config = StarSelfieConfig(
                project_root=root,
                enabled=True,
                gemini_api_key="super-secret-gemini",
                face_swap_url="https://provider.invalid/swap",
                face_swap_api_key="super-secret-face",
                persistent_root=root / "data",
                seed_catalog_path=seed,
            )
            with mock.patch.dict("os.environ", {"OWNER_ID": "123"}, clear=False):
                report = build_report(config)
            self.assertIn("Gemini API key: ✅", report)
            self.assertIn("нет активного героя", report)
            self.assertNotIn("super-secret", report)


if __name__ == "__main__":
    unittest.main()