from neyrobot_prod.provider_config import resolve_text_provider_config


def test_direct_openai_strips_openrouter_model_namespace():
    config = resolve_text_provider_config(
        api_key="sk-direct",
        base_url="",
        model="openai/gpt-4o-mini",
        provider="",
    )

    assert config.provider == "openai"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.model == "gpt-4o-mini"


def test_openrouter_key_keeps_namespaced_model():
    config = resolve_text_provider_config(
        api_key="sk-or-test",
        base_url="",
        model="openai/gpt-4o-mini",
        provider="",
    )

    assert config.provider == "openrouter"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.model == "openai/gpt-4o-mini"


def test_explicit_openrouter_provider_namespaces_openai_model():
    config = resolve_text_provider_config(
        api_key="custom-key",
        base_url="",
        model="gpt-4o-mini",
        provider="openrouter",
    )

    assert config.provider == "openrouter"
    assert config.model == "openai/gpt-4o-mini"


def test_custom_compatible_base_preserves_model_identifier():
    config = resolve_text_provider_config(
        api_key="custom-key",
        base_url="https://llm.example.test/v1",
        model="vendor/model-a",
        provider="compatible",
    )

    assert config.provider == "compatible"
    assert config.base_url == "https://llm.example.test/v1"
    assert config.model == "vendor/model-a"


def test_direct_openai_uses_current_economy_default_when_model_is_empty():
    config = resolve_text_provider_config(
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model="",
        provider="openai",
    )

    assert config.provider == "openai"
    assert config.model == "gpt-5.6-luna"
