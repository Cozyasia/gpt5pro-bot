from pathlib import Path

import pytest

from neyrobot_prod.star_selfie.config import StarSelfieConfig
from neyrobot_prod.star_selfie.qc import BasicImageQC


def test_star_selfie_disabled_needs_no_secrets():
    config = StarSelfieConfig(project_root=Path("."), enabled=False, gemini_api_key="")
    config.validate_runtime()


def test_star_selfie_enabled_requires_provider_settings():
    config = StarSelfieConfig(project_root=Path("."), enabled=True, gemini_api_key="")
    with pytest.raises(RuntimeError) as exc:
        config.validate_runtime()
    assert "GEMINI_API_KEY" in str(exc.value)
    assert "STAR_SELFIE_FACE_SWAP_URL" in str(exc.value)


def test_qc_rejects_provider_json_error():
    result = BasicImageQC().validate(b'{"error":"denied"}' + b" " * 20_000)
    assert not result.accepted
    assert result.reason == "non_image_payload"


def test_qc_accepts_large_jpeg():
    result = BasicImageQC().validate(b"\xff\xd8\xff" + b"0" * 20_000)
    assert result.accepted
