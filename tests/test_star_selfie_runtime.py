from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from neyrobot_prod.star_selfie.config import StarSelfieConfig
from neyrobot_prod.star_selfie.diagnostics import build_report
from neyrobot_prod.star_selfie.providers.http import SegmindFaceSwapRESTTransport
from neyrobot_prod.star_selfie.qc import BasicImageQC


class StarSelfieRuntimeTests(unittest.TestCase):
    def test_star_selfie_disabled_needs_no_secrets(self):
        config = StarSelfieConfig(project_root=Path("."), enabled=False, gemini_api_key="")
        config.validate_runtime()

    def test_star_selfie_enabled_requires_existing_provider_keys(self):
        config = StarSelfieConfig(project_root=Path("."), enabled=True, gemini_api_key="")
        with self.assertRaises(RuntimeError) as exc:
            config.validate_runtime()
        self.assertIn("GEMINI_IMAGE_API_KEY", str(exc.exception))
        self.assertIn("SEGMIND_API_KEY", str(exc.exception))

    def test_config_reuses_existing_render_credentials(self):
        env = {
            "STAR_SELFIE_ENABLED": "1",
            "GEMINI_IMAGE_API_KEY": "gemini-existing",
            "GEMINI_IMAGE_FALLBACK_MODEL": "gemini-existing-model",
            "SEGMIND_API_KEY": "segmind-existing",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            config = StarSelfieConfig.from_env(Path("/app"))
        self.assertEqual(config.gemini_api_key, "gemini-existing")
        self.assertEqual(config.gemini_model, "gemini-existing-model")
        self.assertEqual(config.face_swap_api_key, "segmind-existing")
        self.assertEqual(config.face_swap_provider, "segmind")
        self.assertEqual(config.face_swap_url, "https://api.segmind.com/v1/faceswap-v2")
        config.validate_runtime()

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


class SegmindTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_faceswap_v2_uses_official_fields_and_api_header(self):
        captured = {}

        def fake_request(url, headers, payload, timeout):
            captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
            return b"\xff\xd8\xffresult", "image/jpeg"

        transport = SegmindFaceSwapRESTTransport(
            endpoint="https://api.segmind.com/v1/faceswap-v2",
            api_key="secret",
            timeout_s=123,
        )
        with mock.patch("neyrobot_prod.star_selfie.providers.http._request", side_effect=fake_request):
            result = await transport.swap(source_face=b"\xff\xd8\xffsource", target_scene=b"\x89PNGtarget")

        self.assertEqual(result, b"\xff\xd8\xffresult")
        self.assertEqual(captured["headers"]["x-api-key"], "secret")
        self.assertIn("source_img", captured["payload"])
        self.assertIn("target_img", captured["payload"])
        self.assertEqual(captured["payload"]["input_faces_index"], "0")
        self.assertEqual(captured["payload"]["source_faces_index"], "0")
        self.assertFalse(captured["payload"]["base64"])


if __name__ == "__main__":
    unittest.main()
