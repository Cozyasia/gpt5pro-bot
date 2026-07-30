from pathlib import Path


def test_telegram_flow_is_namespaced_and_feature_flagged():
    source = Path("neyrobot_prod/star_selfie/telegram.py").read_text(encoding="utf-8")
    bootstrap = Path("neyrobot_prod/star_selfie/bootstrap.py").read_text(encoding="utf-8")

    assert '"star_selfie_flow"' in source
    assert '"starselfie:"' in source
    assert 'CommandHandler("star_selfie"' in source
    assert 'CommandHandler("cancel_star_selfie"' in source
    assert 'state.get("step") != "photo"' in source
    assert 'STAR_SELFIE_ENABLED' in bootstrap
    assert 'getattr(app, "_star_selfie_handlers", False)' in bootstrap


def test_bootstrap_import_cannot_break_production_startup():
    source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
    assert "try:" in source
    assert "_install_star_selfie_builder_hook()" in source
    assert "except Exception:" in source


def test_seed_character_stays_inactive_without_reference_files():
    import json

    payload = json.loads(Path("assets/star_selfie/catalog.json").read_text(encoding="utf-8"))
    character = payload["characters"]["roman_abramovich"]
    assert character["active"] is False
    assert len(character["references"]) == 3
