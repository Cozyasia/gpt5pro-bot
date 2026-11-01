import json

import pytest

from ops.neyronix_capability_audit import (
    CAPABILITIES,
    LiveProviderTestGate,
    audit_capabilities,
)


MANDATORY_IDS = {
    "text_chat",
    "documents_pdf_docx",
    "image_analysis",
    "speech_to_text",
    "text_to_speech",
    "live_search",
    "dialog_history",
    "image_generation",
    "image_edit_reference",
    "celebrity_selfie",
    "video_text_to_video",
    "video_image_to_video",
    "video_multi_photo",
    "video_property",
    "video_reels_shorts",
    "video_lipsync",
    "video_multiscene",
    "music_generation",
    "neuroproduction",
    "marketplace",
    "payments_yookassa",
    "payments_cryptobot",
}


def test_inventory_covers_mandatory_product_surface():
    ids = {item.capability_id for item in CAPABILITIES}
    assert MANDATORY_IDS <= ids
    providers = {item.provider for item in CAPABILITIES}
    assert {"OpenAI", "Kling AI", "Seedance", "Google Veo", "HeyGen", "Suno"} <= providers


def test_audit_is_fail_closed_when_source_evidence_is_missing(tmp_path):
    (tmp_path / "main.py").write_text("# empty runtime\n", encoding="utf-8")
    report = audit_capabilities(tmp_path, environ={"OPENAI_API_KEY": "super-secret"})
    text_chat = next(item for item in report["capabilities"] if item["id"] == "text_chat")
    assert text_chat["code_status"] == "missing_evidence"
    assert text_chat["configuration"]["ready"] is True


def test_report_exposes_only_env_presence_never_secret_values(tmp_path):
    (tmp_path / "main.py").write_text("OPENAI_API_KEY cmd_start on_text\n", encoding="utf-8")
    report = audit_capabilities(tmp_path, environ={"OPENAI_API_KEY": "super-secret"})
    payload = json.dumps(report, ensure_ascii=False)
    assert "super-secret" not in payload
    assert report["environment"]["OPENAI_API_KEY"] is True


def test_live_provider_tests_require_explicit_switch_and_positive_budget():
    with pytest.raises(RuntimeError, match="NEYRONIX_ALLOW_LIVE_PROVIDER_TESTS"):
        LiveProviderTestGate.from_environ({})
    with pytest.raises(RuntimeError, match="positive"):
        LiveProviderTestGate.from_environ(
            {"NEYRONIX_ALLOW_LIVE_PROVIDER_TESTS": "1", "NEYRONIX_LIVE_TEST_BUDGET_USD": "0"}
        )
    gate = LiveProviderTestGate.from_environ(
        {"NEYRONIX_ALLOW_LIVE_PROVIDER_TESTS": "1", "NEYRONIX_LIVE_TEST_BUDGET_USD": "2.50"}
    )
    assert gate.budget_usd == 2.5


def test_cryptobot_secret_file_counts_as_presence_without_exposing_value(tmp_path):
    (tmp_path / "main.py").write_text(
        "CRYPTO_PAY_API_TOKEN createInvoice getInvoices\n", encoding="utf-8"
    )
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "cryptobot.env").write_text(
        "CRYPTO_PAY_API_TOKEN=never-print-this\n", encoding="utf-8"
    )

    report = audit_capabilities(tmp_path, environ={}, secret_dir=secret_dir)
    crypto = next(item for item in report["capabilities"] if item["id"] == "payments_cryptobot")
    payload = json.dumps(report, ensure_ascii=False)

    assert crypto["configuration"]["ready"] is True
    assert report["environment"]["CRYPTO_PAY_API_TOKEN"] is True
    assert "never-print-this" not in payload


def test_yookassa_secret_file_requires_complete_direct_pair_without_exposing_values(tmp_path):
    (tmp_path / "main.py").write_text(
        "PreCheckoutQueryHandler on_successful_payment YOOKASSA_PROVIDER_TOKEN "
        "YOO_SHOP_ID YOO_SECRET_KEY\n",
        encoding="utf-8",
    )
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secret_file = secret_dir / "yookassa.env"
    secret_file.write_text(
        "YK_ID=never-print-shop-id\nYK_KEY=never-print-shop-key\n",
        encoding="utf-8",
    )

    report = audit_capabilities(tmp_path, environ={}, secret_dir=secret_dir)
    yookassa = next(item for item in report["capabilities"] if item["id"] == "payments_yookassa")
    payload = json.dumps(report, ensure_ascii=False)

    assert yookassa["configuration"]["ready"] is True
    assert report["environment"]["YK_ID"] is True
    assert report["environment"]["YK_KEY"] is True
    assert "never-print-shop" not in payload

    secret_file.write_text("YK_ID=only-one-half\n", encoding="utf-8")
    incomplete = audit_capabilities(tmp_path, environ={}, secret_dir=secret_dir)
    incomplete_yookassa = next(
        item for item in incomplete["capabilities"] if item["id"] == "payments_yookassa"
    )
    assert incomplete_yookassa["configuration"]["ready"] is False

