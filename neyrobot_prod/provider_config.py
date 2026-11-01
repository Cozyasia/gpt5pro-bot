"""Fail-safe provider/model normalization for OpenAI-compatible text APIs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str


def resolve_text_provider_config(
    *,
    api_key: str,
    comet_api_key: str = "",
    base_url: str,
    model: str,
    provider: str,
) -> TextProviderConfig:
    key = str(api_key or "").strip()
    comet_key = str(comet_api_key or "").strip()
    base = str(base_url or "").strip().rstrip("/")
    selected_model = str(model or "").strip() or "gpt-5.6-luna"
    selected_provider = str(provider or "").strip().lower()

    uses_comet = (
        selected_provider in {"comet", "cometapi"}
        or "api.cometapi.com" in base.lower()
    )
    if uses_comet:
        comet_base = base if "api.cometapi.com" in base.lower() else "https://api.cometapi.com/v1"
        return TextProviderConfig(
            provider="comet",
            base_url=comet_base,
            model=selected_model,
            api_key=comet_key or key,
        )

    uses_openrouter = (
        key.startswith("sk-or-")
        or selected_provider == "openrouter"
        or "openrouter.ai" in base.lower()
    )
    if uses_openrouter:
        if "/" not in selected_model:
            selected_model = f"openai/{selected_model}"
        return TextProviderConfig(
            provider="openrouter",
            base_url=base or "https://openrouter.ai/api/v1",
            model=selected_model,
            api_key=key,
        )

    is_direct_openai = not base or "api.openai.com" in base.lower()
    if is_direct_openai:
        if selected_model.startswith("openai/"):
            selected_model = selected_model.removeprefix("openai/")
        return TextProviderConfig(
            provider="openai",
            base_url=base or "https://api.openai.com/v1",
            model=selected_model,
            api_key=key,
        )

    return TextProviderConfig(
        provider=selected_provider or "compatible",
        base_url=base,
        model=selected_model,
        api_key=key,
    )


__all__ = ["TextProviderConfig", "resolve_text_provider_config"]
