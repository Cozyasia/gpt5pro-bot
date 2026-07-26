from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v209_is_bootstrapped_after_v208() -> None:
    source = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
    assert "install_selfie_v208" in source
    assert "install_selfie_v209" in source
    assert source.index("install_selfie_v209") > source.index("install_selfie_v208")


def test_v209_is_installed_from_guaranteed_main_bootstrap_after_v207() -> None:
    source = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    install_body = source[source.index("def install() -> None:"):]
    assert "from neyrobot_prod.selfie_v209_canonical import install" in source
    assert "_install_selfie_runtime_v207()" in install_body
    assert "_install_selfie_v209()" in install_body
    assert install_body.index("_install_selfie_v209()") > install_body.index("_install_selfie_runtime_v207()")


def test_v209_owns_public_handlers_at_higher_priority() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v209_canonical.py").read_text(encoding="utf-8")
    assert 'VERSION = "v209-selfie-canonical-binding-2026-07-26"' in source
    assert "v208._public_callback" in source
    assert "v208._public_media" in source
    assert "v208._public_text" in source
    assert "group=-2044" in source
    assert "group=-2042" in source
    assert "runtime_v207.patch_runtime = lambda: True" in source


def test_v208_flow_requires_two_user_photos_and_country_catalogue() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v208_overlay.py").read_text(encoding="utf-8")
    assert "Селфи 1/2" in source
    assert "Селфи 2/2" in source
    assert "len(user_images) != 2" in source
    assert "references_per_request=5" in source
    assert "🇷🇺 Русские герои" in source
    assert "🇺🇸 Американские герои" in source


def test_video_cannot_fall_back_to_legacy_one_selfie_flow() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v209_canonical.py").read_text(encoding="utf-8")
    assert "reject_non_photo_selfie" in source
    assert 'getattr(filters, "VIDEO", None)' in source
    assert "нужны именно две отдельные фотографии, не видео" in source
