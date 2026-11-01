import model_policy_v115 as policy


def test_economy_defaults_upgrade_legacy_text_models(monkeypatch):
    monkeypatch.setenv("GENERAL_MODEL_BASIC", "gpt-4o-mini")
    monkeypatch.setenv("GENERAL_MODEL_PRO", "gpt-5-mini")
    monkeypatch.delenv("GENERAL_MODEL_ULTIMATE", raising=False)

    policy._set_policy_environment()

    assert policy.os.environ["GENERAL_MODEL_BASIC"] == "gpt-5.6-luna"
    assert policy.os.environ["GENERAL_MODEL_PRO"] == "gpt-5.6-luna"
    assert policy.os.environ["GENERAL_MODEL_ULTIMATE"] == "gpt-5.6-luna"


def test_current_gpt56_prices_match_standard_api_rates():
    assert policy.CURRENT_PRICES["gpt-5.6-luna"] == (0.20, 1.20)
    assert policy.CURRENT_PRICES["gpt-5.6-terra"] == (2.00, 12.00)
    assert policy.CURRENT_PRICES["gpt-5.6-sol"] == (4.00, 20.00)
