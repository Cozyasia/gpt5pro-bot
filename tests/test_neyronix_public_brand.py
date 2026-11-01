from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployable_user_facing_sources_do_not_expose_legacy_brand():
    public_sources = (
        "main.py",
        "render.yaml",
        "env.sample",
        "neyrobot_prod/credit_store_v201.py",
        "neyrobot_prod/studio_prompt_handlers.py",
        "neyrobot_prod/heygen_adapter.py",
        "neyrobot_prod/heygen_talking_avatar.py",
    )
    forbidden = ("Neyro-Bot GPT 5 Studio", "GPT5 Studio AI")

    violations = []
    for relative_path in public_sources:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for legacy_name in forbidden:
            if legacy_name in text:
                violations.append(f"{relative_path}: {legacy_name}")

    assert not violations, "legacy public brand remains: " + ", ".join(violations)


def test_public_payment_and_provider_labels_use_neyronix():
    credit_store = (ROOT / "neyrobot_prod/credit_store_v201.py").read_text(
        encoding="utf-8"
    )
    heygen = (ROOT / "neyrobot_prod/heygen_adapter.py").read_text(encoding="utf-8")
    avatar = (ROOT / "neyrobot_prod/heygen_talking_avatar.py").read_text(
        encoding="utf-8"
    )

    assert "Пополнение баланса NEYRONIX" in credit_store
    assert 'title: str = "NEYRONIX Studio"' in heygen
    assert 'or "NEYRONIX Studio"' in avatar
