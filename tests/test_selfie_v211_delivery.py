from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v211_is_installed_after_v210() -> None:
    source = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    body = source[source.index("def install() -> None:"):]
    assert "_install_selfie_v210()" in body
    assert "_install_selfie_v211()" in body
    assert body.index("_install_selfie_v211()") > body.index("_install_selfie_v210()")


def test_v211_retries_telegram_delivery_without_regeneration() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v211_delivery.py").read_text(encoding="utf-8")
    assert 'VERSION = "v211-selfie-delivery-retry-2026-07-26"' in source
    assert "async def _deliver" in source
    assert "reply_document" in source
    assert "reply_photo" in source
    assert "write_timeout=timeout" in source
    assert "max_side=1280" in source
    assert source.count("await v208._comet_generate") == 1


def test_v211_suppresses_duplicate_generic_failure_and_protects_credits() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v211_delivery.py").read_text(encoding="utf-8")
    assert 'kwargs["silent_failure"] = True' in source
    assert "Credits remain chargeable only after a result has actually reached the chat" in source
    assert "Средства не должны списываться" in source
    assert 'result = {"ok": False}' in source
    assert 'result["ok"] = bool(delivered)' in source


def test_v211_pins_a_longer_provider_timeout_and_version_chain() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v211_delivery.py").read_text(encoding="utf-8")
    assert 'os.environ["COMET_SELFIE_TIMEOUT_S"]' in source
    assert "max(300.0, configured)" in source
    assert "v208._generate = generate" in source
    assert "v210.VERSION = VERSION" in source
    assert 'runtime.CELEBRITY_SELFIE_ROUTE = "v211-comet-five-reference-delivery-retry"' in source
